#!/usr/bin/env python3
"""Read-only Mac Demo Common E1 certificate and runnable readiness census.

Never issues a customer order, cash operation, ZooKeeper write, or READY.
Counts signed on-disk prerequisites without treating file existence as valid
cryptographic verification. Cryptographic proof must be done by Common itself.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

LINE = re.compile(
    r"^(P\d{3})\|([1-9]\d*)\|(OrderSvr[AB]|TradeSvr[AB])\|"
    r"(OrderSvr[AB]|TradeSvr[AB])\|(STRICT_QUORUM)\|(READY|RECOVERING)$"
)
ROOT = pathlib.Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data")
DOCKER_NAMES = {
    "OrderSvrA": "dc-saas-ordersvr",
    "OrderSvrB": "dc-saas-ordersvr-b",
    "TradeSvrA": "dc-saas-tradesvr",
    "TradeSvrB": "dc-saas-tradesvr-b",
}


def parsed_manifest(text):
    lines = text.splitlines()
    records = {}
    for line in lines:
        matched = LINE.fullmatch(line.strip())
        if matched:
            part, epoch, primary, replica, policy, phase = matched.groups()
            if part in records:
                raise ValueError("duplicate Common partition " + part)
            if primary == replica:
                raise ValueError("non-independent original RF2 " + part)
            records[part] = dict(epoch=int(epoch), primary=primary,
                                 replica=replica, policy=policy, phase=phase)
    return records


def zk_manifest(service):
    command = ["docker", "exec", "-i", "dc-saas-zookeeper", "sh",
               "-lc", "zkCli.sh -server 127.0.0.1:32181"]
    result = subprocess.run(
        command, input=f"get /otc/demo-real-common/{service}/manifest\nquit\n",
        text=True, capture_output=True, timeout=25, check=False,
    )
    if "Node does not exist:" in result.stdout or result.returncode not in (0, 1):
        raise RuntimeError(f"Common {service} manifest inaccessible")
    records = parsed_manifest(result.stdout)
    if len(records) != 256:
        raise RuntimeError(f"Common {service} returned {len(records)} / 256 partitions")
    return records


def count_original(service, members, root):
    signed = genesis = birth = sealed = 0
    for partition, r in members.items():
        for voter in (r["primary"], r["replica"]):
            local = root / "common-demo-original-e1" / service / voter / partition
            signed += (local / "receipts" / f"{voter}.rsa2048").is_file()
            genesis += (local / "node-voter" /
                        f"original-e1-{voter}.genesis").is_file()
            birth += (root / "common-demo-original-e1" / service / voter /
                      "original-wal" / partition /
                      "original-e1-zero-ack.birth").is_file()
        # Original E1 helper seals the two-voter quorum in the canonical
        # service-level namespace. It is NOT below the primary voter root.
        quorum_root = root / "common-demo-original-e1" / service / "sealed" / partition
        sealed += ((quorum_root / "genesis-e1.quorum").is_file()
                   and (quorum_root / "genesis-e1.snapshot").is_file())
    return dict(expected_voter_records=512, rsa_receipts_present=signed,
                original_images_present=genesis, zero_ack_births_present=birth,
                sealed_quorum_present=sealed, expected_quorums=256)


def count_original_source_config(service, config_root):
    """Configuration completeness only; never grants signed membership."""
    prefix = "order" if service == "OrderSvr" else "trade"
    count = {}
    for node in ("A", "B"):
        file = config_root / f"{service}{node}.properties"
        properties = {}
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
        required = (
            "primary", "replica", "primaryRsaAlias", "replicaRsaAlias",
            "primaryPhysicalHost", "replicaPhysicalHost", "originalSignedQuorum",
            "localDurableGenesis", "durableTransactionRoot",
            "primaryOriginalWalRoot", "replicaOriginalWalRoot",
        )
        base = f"{prefix}.common.nodeRuntime.freshE1."
        present = sum(
            all(properties.get(f"{base}P{i:03d}.{k}") for k in required)
            for i in range(256)
        )
        count[f"{service}{node}"] = dict(
            complete_partition_sources=present,
            expected_partition_sources=256,
            real_business_inspection_opt_in=(
                properties.get(f"{prefix}.common.nodeRuntime.inspectFencedBusiness") == "true"),
            certified_genesis_install_opt_in=(
                properties.get(f"{prefix}.common.nodeRuntime.installFencedFreshGenesis") == "true"),
            complete_first_activation_opt_in=(
                properties.get(f"{prefix}.common.nodeRuntime.stageOriginalFleet") == "true"),
        )
    return count


def current_processes():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        text=True, capture_output=True, timeout=12, check=True
    )
    names = set(result.stdout.splitlines())
    return {node: name in names for node, name in DOCKER_NAMES.items()}


def run(root, config_root=None):
    if config_root is None:
        config_root = root.parent / "control" / "common-t167-direct-live"
    services = {}
    for service in ("order", "trade"):
        records = zk_manifest(service)
        mismatches = sorted(p for p, r in records.items()
                            if r["epoch"] != 1 or r["phase"] != "RECOVERING"
                            or r["policy"] != "STRICT_QUORUM")
        srv = "OrderSvr" if service == "order" else "TradeSvr"
        services[service] = dict(
            manifest_partitions=len(records),
            ready_partitions=sum(r["phase"] == "READY" for r in records.values()),
            untrusted_or_non_e1=mismatches,
            original_files=count_original(srv, records, root),
            recovery_source_config=count_original_source_config(srv, config_root))
    runtime = current_processes()
    files_complete = all(runtime.values()) and all(
        v["original_files"]["original_images_present"] == 512
        and v["original_files"]["rsa_receipts_present"] == 512
        and v["original_files"]["zero_ack_births_present"] == 512
        and v["original_files"]["sealed_quorum_present"] == 256
        for v in services.values())
    # This check is deliberately insufficient for authorization: hashes, RSA
    # signatures, original WAL and both replay transaction ledgers still
    # require independent Common cryptographic verification.
    return dict(business_ready_confirmed_by_this_check=False,
                filesystem_census_only=True,
                original_file_prerequisites_complete=files_complete,
                containers=runtime, services=services)


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--data-root", type=pathlib.Path, default=ROOT)
    cli.add_argument("--config-root", type=pathlib.Path)
    options = cli.parse_args()
    try:
        result = run(options.data_root, options.config_root)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print("COMMON_DEMO_PREFLIGHT_BLOCKED:", error, file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
