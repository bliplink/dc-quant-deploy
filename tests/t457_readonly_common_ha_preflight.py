#!/usr/bin/env python3
"""T457 read-only release gate: inspect real Order/Trade Common HA wiring.

No writes to Docker, ZooKeeper, WAL, keys, SQL, or service state.
A ZK READY snapshot is not considered a physical customer-writing proof.
"""
import argparse
from collections import Counter
import json
import re
import subprocess
import sys

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PARTITION = re.compile(
    r"^(P\d{3})\|(\d+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)$"
)
WATCH = re.compile(r'^"common-failover-cold-\d+"', re.MULTILINE)


class ProbeError(RuntimeError):
    pass


def execute(args, input_text=None, timeout=35):
    try:
        proc = subprocess.run(
            args, input=input_text, text=True, capture_output=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError("probe unavailable: " + type(exc).__name__) from exc
    if proc.returncode != 0:
        raise ProbeError(
            "probe returned nonzero ({}): {}".format(
                proc.returncode, " ".join(args[:3])
            )
        )
    return proc.stdout


def parse_manifest(output):
    """Extract the actual NPC1 service manifest, not a separate ZK status line."""
    if "NPC1|" not in output:
        raise ProbeError("NPC1 service manifest header absent")
    rows = {}
    for raw in output.splitlines():
        match = PARTITION.fullmatch(raw.strip())
        if not match:
            continue
        partition, epoch, primary, replica, policy, state = match.groups()
        if partition in rows:
            raise ProbeError("duplicate physical assignment: " + partition)
        if primary == replica or not primary or not replica:
            raise ProbeError("invalid primary/replica pair: " + partition)
        rows[partition] = dict(
            epoch=int(epoch), primary=primary, replica=replica,
            policy=policy, state=state,
        )
    expected = {"P{:03d}".format(i) for i in range(256)}
    if set(rows) != expected:
        raise ProbeError(
            "manifest not exactly 256 unique partitions (found {})".format(
                len(rows)
            )
        )
    return rows


def manifest_summary(rows):
    homes = Counter(x["primary"] for x in rows.values())
    states = Counter(x["state"] for x in rows.values())
    policies = Counter(x["policy"] for x in rows.values())
    return {
        "partitions": len(rows),
        "primary_counts": dict(sorted(homes.items())),
        "states": dict(sorted(states.items())),
        "policies": dict(sorted(policies.items())),
        "P060": rows["P060"],
        "balanced_128_128": sorted(homes.values()) == [128, 128],
        "all_ready": states == {"READY": 256},
    }


def zk_manifest(container, path):
    text = execute(
        ["docker", "exec", "-i", container, "zkCli.sh", "-server",
         "127.0.0.1:2181"],
        "get {}\nquit\n".format(path),
        timeout=45,
    )
    return manifest_summary(parse_manifest(text))


def common_sha(container, service):
    # Controlled static service name. Never read/emit other application config.
    if service not in {"OrderSvr", "TradeSvr"}:
        raise ProbeError("unsupported service")
    folder = "/srv/dc/dc/{}/lib".format(service)
    out = execute(
        ["docker", "exec", container, "sh", "-c",
         'set -eu; set -- ' + folder +
         '/com.app.common-*.jar; [ "$#" -eq 1 ] && [ -f "$1" ] '
         '|| exit 91; sha256sum "$1"'],
    )
    digest = out.strip().split()[0] if out.strip() else ""
    if not SHA256.fullmatch(digest):
        raise ProbeError("Common JAR SHA256 unavailable")
    return digest


def common_watch_threads(container):
    # Common reuses two shared control threads across all 128 local Replicas.
    # A Spring process with no such threads has not armed its Watch lifecycle.
    text = execute(["docker", "exec", container, "jstack", "1"], timeout=50)
    return len(WATCH.findall(text))


def network_mode(container):
    return execute(
        ["docker", "inspect", container,
         "--format", "{{.HostConfig.NetworkMode}}"]
    ).strip()


def verify(result, expected_sha):
    failures = []
    for service in ("order", "trade"):
        census = result["manifest"].get(service, {})
        if census.get("partitions") != 256 or not census.get("balanced_128_128"):
            failures.append(service.upper() + "_256_HOME_CENSUS_FAIL")
        if not census.get("all_ready"):
            failures.append(service.upper() + "_ZK_NOT_ALL_READY")
    common = result.get("nodes", {})
    hashes = {x.get("common_sha") for x in common.values()}
    if len(hashes) != 1 or expected_sha not in hashes:
        failures.append("COMMON_JAR_SHA_MISMATCH")
    for name, node in common.items():
        if node.get("watch_threads", 0) <= 0:
            failures.append(name.upper().replace("-", "_") + "_AUTO_WATCH_ABSENT")
        if node.get("network_mode") != "host":
            failures.append(name.upper().replace("-", "_") + "_NETWORK_MODE_UNEXPECTED")
    if len(common) != 4:
        failures.append("FOUR_NODE_CENSUS_INCOMPLETE")
    return failures


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zk-container", required=True)
    p.add_argument("--order-manifest", required=True)
    p.add_argument("--trade-manifest", required=True)
    for name in ("order-a", "order-b", "trade-a", "trade-b"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--expected-common-sha", required=True)
    args = p.parse_args()
    if not SHA256.fullmatch(args.expected_common_sha):
        p.error("--expected-common-sha must be an exact lowercase SHA-256")
    result = {
        "read_only": True,
        "purpose": "T457 physical release gate",
        "expected_common_sha": args.expected_common_sha,
        "manifest": {},
        "nodes": {},
        "issues": [],
        "verdict": "NO_GO",
    }
    targets = {
        "order-a": (args.order_a, "OrderSvr"),
        "order-b": (args.order_b, "OrderSvr"),
        "trade-a": (args.trade_a, "TradeSvr"),
        "trade-b": (args.trade_b, "TradeSvr"),
    }
    try:
        result["manifest"]["order"] = zk_manifest(
            args.zk_container, args.order_manifest
        )
        result["manifest"]["trade"] = zk_manifest(
            args.zk_container, args.trade_manifest
        )
        for name, (container, service) in targets.items():
            result["nodes"][name] = {
                "container": container,
                "common_sha": common_sha(container, service),
                "watch_threads": common_watch_threads(container),
                "network_mode": network_mode(container),
            }
        result["issues"] = verify(result, args.expected_common_sha)
        if not result["issues"]:
            # This gate checks prerequisites, not business-correctness/HA proof.
            result["verdict"] = "PREFLIGHT_PASS_NOT_HA_ACCEPTANCE"
    except ProbeError as exc:
        result["issues"].append("UNVERIFIED_OR_UNAVAILABLE_EVIDENCE")
        result["diagnostic"] = str(exc)[:200]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["verdict"].startswith("PREFLIGHT_PASS") else 2


if __name__ == "__main__":
    sys.exit(main())
