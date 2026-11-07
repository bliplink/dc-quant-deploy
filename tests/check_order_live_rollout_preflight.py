#!/usr/bin/env python3
"""Read-only fail-closed preflight before *live* certified Order A/B replacement.

This is not an HA implementation or a Common election/authorization tool.
It refuses upgrades when the currently serving A/B is in manual Genesis-only
mode, has poisoned writers, carries a mismatched Common binary, or when
customer Robot/market activity is degraded. Use a fresh isolated namespace
instead; never clear a poisoned same-Epoch Primary with a script.
"""
import argparse
import json
import re
import subprocess
import sys


def shell(*argv, timeout=35):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError("%s failed (code=%d): %s" % (
            argv[0], proc.returncode, (proc.stderr or proc.stdout)[-180:]))
    # Docker logs preserves the application's original stdout/stderr stream.
    # Common write-fence exceptions are often in STDERR, not stdout.
    return proc.stdout + (proc.stderr if argv[:2] == ("docker", "logs") else "")


def inspect(name):
    result = json.loads(shell("docker", "inspect", name, timeout=15))
    if len(result) != 1:
        raise RuntimeError("EXPECTED_ONE_CONTAINER")
    return result[0]


def parse_property(raw, key):
    matches = [line.partition("=")[2].strip() for line in raw.splitlines()
               if line.strip().startswith(key + "=")]
    return matches[-1] if len(matches) == 1 else None


def assess_node(meta, props, common_digest, recent_log):
    """Deterministic testable policy; Docker/credentials remain outside."""
    reasons = []
    if meta.get("State", {}).get("Status") != "running":
        reasons.append("NODE_NOT_RUNNING")
    if parse_property(props, "order.common.nodeRuntime.enabled") != "true":
        reasons.append("COMMON_CERTIFIED_RUNTIME_DISABLED")
    if parse_property(props, "order.common.nodeRuntime.phase") != "READY":
        reasons.append("COMMON_CERTIFIED_PHASE_NOT_READY")
    if parse_property(props, "order.common.nodeRuntime.automaticRecovery") != "true":
        reasons.append("AUTO_RECOVERY_DISABLED_NO_SAFE_ROLLING_REJOIN")
    if not re.fullmatch(r"[a-f0-9]{64}", common_digest or ""):
        reasons.append("COMMON_JAR_PHYSICAL_SHA_MISSING")
    if "Common poisoned primary Epoch cannot renew" in recent_log:
        reasons.append("PRIMARY_EPOCH_IRREVOCABLY_POISONED")
    if "ORDER_COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED" in recent_log:
        reasons.append("CERTIFIED_PARTITION_WRITES_DENIED")
    if "COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT" in recent_log:
        reasons.append("COMMON_CERTIFIED_CENSUS_NOT_READY")
    return reasons


def assess_robots(rows):
    reasons = []
    if not rows:
        return ["ROBOT_STATE_EMPTY"]
    for status, count in rows:
        if status != "RUNNING" and count > 0:
            reasons.append("ROBOT_NOT_RUNNING:" + status + ":" + str(count))
    if sum(count for status, count in rows if status == "RUNNING") < 1:
        reasons.append("NO_RUNNING_TRADING_ROBOTS")
    return reasons


def mysql_robots(container):
    sql = "SELECT runtime_status,COUNT(*) FROM dc_tenant_robot GROUP BY runtime_status"
    raw = shell("docker", "exec", container, "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N dc -e ' +
                json.dumps(sql), timeout=20)
    parsed = []
    for row in raw.splitlines():
        status, count = row.split("\t")
        parsed.append((status, int(count)))
    return parsed


def node_info(name):
    meta = inspect(name)
    props = shell("docker", "exec", name, "sh", "-c",
                  "cat /srv/dc/dc/OrderSvr/config/application.properties", timeout=15)
    # Read the mounted Common binary, not an untrusted/old Docker label.
    jars = shell("docker", "exec", name, "sh", "-c",
                 "find /srv/dc/dc/OrderSvr/lib -maxdepth 1 -type f "
                 "-name 'com.app.common*.jar' -print", timeout=18).splitlines()
    if len(jars) != 1:
        raise RuntimeError("EXACT_ONE_COMMON_RUNTIME_JAR_REQUIRED")
    raw = shell("docker", "exec", name, "sha256sum", jars[0], timeout=18)
    digest = raw.split()[0] if raw.split() else ""
    log = shell("docker", "logs", "--since", "90s", name, timeout=22)
    return meta, props, digest, log


def run(args):
    reasons = []
    digests = []
    states = {}
    for node in (args.order_a, args.order_b):
        try:
            meta, props, digest, log = node_info(node)
            states[node] = {"running": meta.get("State", {}).get("Status") == "running",
                            "automaticRecovery": parse_property(
                                props, "order.common.nodeRuntime.automaticRecovery"),
                            "common_sha256": digest}
            digests.append(digest)
            reasons.extend(node + ":" + cause for cause in
                           assess_node(meta, props, digest, log))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            reasons.append(node + ":PREFLIGHT_UNAVAILABLE:" + type(exc).__name__)
    if len(digests) != 2 or digests[0] != digests[1]:
        reasons.append("ORDER_AB_COMMON_RUNTIME_SHA_MISMATCH")
    try:
        robots = mysql_robots(args.mysql)
        reasons.extend(assess_robots(robots))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        robots = []
        reasons.append("ROBOT_CENSUS_UNAVAILABLE")
    result = {"status": "SAFE_TO_ATTEMPT_ROLLING_VALIDATION" if not reasons
              else "NO_GO_ROLLING_UPGRADE", "ha_sigkill_verified": False,
              "order_nodes": states, "robot_status": dict(robots),
              "reasons": reasons}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not reasons else 2


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--order-a", default="otc-t531-order-a-e2-abcontrol")
    cli.add_argument("--order-b", default="otc-t531-order-b-e2-abcontrol")
    cli.add_argument("--mysql", default="otc-t529-fresh-mysql")
    sys.exit(run(cli.parse_args()))