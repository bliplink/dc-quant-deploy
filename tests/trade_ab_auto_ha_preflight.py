#!/usr/bin/env python3
"""Fail-closed, redacted configuration gate for symmetric Trade A/B recovery.

This tool NEVER reads key material into its result, changes runtime config,
modifies ZooKeeper, or treats the mere presence of keys as proof of replication.
It checks the prerequisites for starting real full-fleet recovery validation.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

PREFIX = "trade.cluster.recovery."
PRIVATE_OR_TRUST = (
    "head.rsaPrivateKeyBase64",
    "read.readerPublicKeyBase64",
    "replica.autoWarm.sourcePublicKeyBase64",
    "replica.autoWarm.readerRsaPrivateKeyBase64",
)

def parse_properties(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError("Trade configuration file not found: " + str(path))
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "!")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values

def blockers(node: str, own: dict[str, str], peer: dict[str, str], *, mode: str = "fleet", partition: str = "P090") -> list[str]:
    if node not in ("A", "B"):
        raise ValueError("exact Trade A/B identity required")
    if mode not in ("fleet", "pilot"):
        raise ValueError("mode must be pilot or fleet")
    if mode == "pilot" and not re.fullmatch(r"P[0-9]{3}", partition):
        raise ValueError("pilot partition must be an exact Pxxx")
    peer_node = "TradeSvrB" if node == "A" else "TradeSvrA"
    peer_port = "19222" if node == "A" else "19221"
    problems: list[str] = []

    def require_enabled(suffix: str) -> None:
        name = PREFIX + suffix
        if own.get(name) != "true":
            problems.append(suffix + ": not enabled")

    def require_equal(suffix: str, expected: str) -> None:
        name = PREFIX + suffix
        if own.get(name, "") != expected:
            problems.append(suffix + ": expected " + expected)

    def require_material(suffix: str) -> None:
        name = PREFIX + suffix
        if not own.get(name, "").strip():
            problems.append(suffix + ": not configured (value always redacted)")

    for flag in (
        "certifiedRecipient.enabled",
        "head.enabled",
        "data.enabled",
        "manifest.enabled",
        "replica.autoWarm.enabled",
        "replica.electedBootstrap.enabled",
        "replica.genesisReceipt.enabled",
        "replica.physicalReceipt.enabled",
        "replica.physicalHealth.enabled",
        "genesisObserver.enabled",
        "genesisObserver.replicaHealthEnabled",
    ):
        require_enabled(flag)
    for suffix in ("replica.electedBootstrap.fleetEnabled", "genesisObserver.fleetEnabled"):
        if mode == "pilot":
            # The Java scheduler defaults OFF. An omitted fleet flag is safe;
            # but explicit fleet=true would violate P090-only fault injection.
            if own.get(PREFIX + suffix, "false") != "false":
                problems.append(suffix + ": pilot requires disabled fleet")
        else:
            require_equal(suffix, "true")
    require_equal("replica.autoWarm.sourceNode", peer_node)
    require_equal("replica.autoWarm.sourcePort", peer_port)
    require_equal("genesisObserver.targetNode", peer_node)
    require_equal("genesisObserver.targetPort", peer_port)
    if own.get(PREFIX + "genesisObserver.transferEnabled", "false") == "true":
        problems.append("genesisObserver.transferEnabled: must be false during replica health recovery")
    own_pilot = own.get(PREFIX + "replica.autoWarm.pilotPartition", "")
    if not re.fullmatch(r"P[0-9]{3}", own_pilot):
        problems.append("replica.autoWarm.pilotPartition: exact Pxxx pilot required")
    elif mode == "pilot" and own_pilot != partition:
        problems.append("replica.autoWarm.pilotPartition: expected " + partition)
    if mode == "pilot":
        require_equal("genesisObserver.pilotPartition", partition)
    for material in PRIVATE_OR_TRUST:
        require_material(material)
    require_material("certifiedRecipient.privateRoot")

    # Both logical roles must own a separate real signing credential. Never
    # infer cross-node trust from a secret belonging to the opposite node.
    if not peer.get(PREFIX + "head.rsaPrivateKeyBase64", "").strip():
        problems.append("peer.head.rsaPrivateKeyBase64: peer has no independent RSA signer")
    if not peer.get(PREFIX + "replica.autoWarm.readerRsaPrivateKeyBase64", "").strip():
        problems.append("peer.replica.autoWarm.readerRsaPrivateKeyBase64: peer cannot sign an independent physical receipt")
    return problems

def inspect(config_root: Path, *, mode: str = "fleet", partition: str = "P090") -> dict[str, list[str]]:
    a = parse_properties(config_root / "TradeSvrA/config/application.properties")
    b = parse_properties(config_root / "TradeSvrB/config/application.properties")
    return {"Trade-A": blockers("A", a, b, mode=mode, partition=partition),
            "Trade-B": blockers("B", b, a, mode=mode, partition=partition)}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("pilot", "fleet"), default="fleet",
                        help="pilot keeps both fleet schedulers OFF (default: fleet)")
    parser.add_argument("--partition", default="P090",
                        help="exact Pxxx pilot partition (default: P090)")
    args = parser.parse_args()
    report = inspect(args.config_root, mode=args.mode, partition=args.partition)
    print("VALIDATION_SCOPE: " + (args.partition if args.mode == "pilot" else "256-partition fleet"))
    for name, issues in report.items():
        print(name + " " + (args.partition + "-pilot" if args.mode == "pilot" else "full-auto-recovery") + "-config=" + ("READY_FOR_LIVE_PROOF" if not issues else "BLOCKED"))
        for problem in issues:
            print("  - " + problem)
    if any(report.values()):
        print("RESULT: BLOCKED; no ZK ACK/READY, financial audit or physical failover may be inferred")
        return 2
    print("RESULT: CONFIG_PREREQUISITES_ONLY; independent key pairing, real ACK, SIGKILL and financial audits are NOT verified")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())