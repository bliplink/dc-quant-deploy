#!/usr/bin/env python3
"""T363 read-only guard: fresh WAL cannot inherit a previously serving ZK Epoch.
No Docker writes, no ZK CAS, no signature generation, no secrets output.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

def properties(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing/nonregular original signed configuration")
    parsed = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line[0] in "#!":
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed

def audit(config: dict, original_order: Path, original_trade: Path) -> dict:
    services = config["services"]
    report = {}
    for svc, envprefix, label in (
        ("ordersvr", "order", "OrderSvr"),
        ("tradesvr", "trade", "TradeSvr"),
    ):
        original = properties(original_order if svc == "ordersvr" else original_trade)
        manifest = original.get(f"{envprefix}.common.control.manifestPath", "")
        birthplace = original.get(f"{envprefix}.common.nodeRuntime.freshE1.namespace", "")
        expected = f"{birthplace.rstrip('/')}/manifest"
        if not manifest or not birthplace or manifest != expected:
            raise ValueError(f"{label}: original signed control lineage inconsistent")
        nodes = [svc, svc+"-b"]
        roots = []
        for node in nodes:
            if node not in services:
                raise ValueError(f"{node}: B cluster profile missing from composed service census")
            c = services[node]
            env = c.get("environment", {})
            if isinstance(env, list):
                env = dict(line.split("=", 1) for line in env if "=" in line)
            flags = env.get("JAVA_OPTS", "")
            target = f"-D{envprefix}.common.nodeRuntime.dataRoot="
            configured = [w[len(target):] for w in flags.split() if w.startswith(target)]
            if len(configured) != 1:
                raise ValueError(f"{node}: exact fresh WAL root required")
            roots.append(configured[0])
            readonly_birth = [v for v in c.get("volumes", [])
                if v.get("target") == "/srv/dc/data/t318-born" and v.get("read_only")]
            if len(readonly_birth) != 1:
                raise ValueError(f"{node}: original birth must be read-only")
        if roots[0] == roots[1] or not all("/t361-fresh/" in r for r in roots):
            raise ValueError(f"{label}: A/B fresh WAL roots not isolated")
        # This is a deliberately conservative NO-GO. The historical
        # application properties point at a previously serving namespace.
        # A fresh empty WAL has NO independently signed committed-head
        # checkpoint of that namespace, regardless of valid E1 birth files.
        report[label] = {
            "root_pattern": "t361-fresh A/B isolated",
            "historical_namespace": "same previously serving signed E2 namespace",
            "original_genesis": "read-only mounted; not authorization for fresh E2 WAL",
            "ready": False,
            "reason": "FRESH_WAL_REUSES_PRIOR_ZK_EPOCH_WITHOUT_CERTIFIED_CHECKPOINT",
        }
    for db, suffix, target in (
        ("mysql", "t361-fresh-mysql", "/var/lib/mysql"),
        ("clickhouse", "t361-fresh-clickhouse", "/var/lib/clickhouse"),
    ):
        volume = [v for v in services[db].get("volumes", []) if v.get("target") == target]
        if len(volume) != 1 or suffix not in volume[0].get("source", ""):
            raise ValueError(f"{db}: full fresh DB volume isolation missing")
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-properties", type=Path, required=True)
    parser.add_argument("--trade-properties", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(json.load(sys.stdin), args.order_properties, args.trade_properties)
        print("T363_FRESH_CLUSTER_LINEAGE_NOGO "+json.dumps(report, sort_keys=True))
        return 2
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
        print("T363_FRESH_CLUSTER_CONFIG_INVALID "+str(exc), file=sys.stderr)
        return 4

if __name__ == "__main__":
    sys.exit(main())
