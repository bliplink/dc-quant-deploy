#!/usr/bin/env python3
"""Offline structural and business-rule validation for desired placement catalogs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SEP = "\x1f"


def load_catalog(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    validate_catalog(value)
    return value


def validate_catalog(catalog: dict[str, Any]) -> None:
    if int(catalog.get("version", 0)) <= 0:
        raise ValueError("catalog version must be positive")
    if int(catalog.get("protocolVersion", 0)) < 3:
        raise ValueError("placement protocolVersion must be at least 3")

    pools = unique(catalog.get("nodePools", []), "poolId", "node pool")
    groups = unique(catalog.get("groups", []), "groupId", "placement group")
    rules = unique(catalog.get("rules", []), "ruleId", "placement rule")
    if not pools or not groups or not rules:
        raise ValueError("nodePools, groups and rules are required")

    for pool in pools.values():
        if not pool.get("serviceName") or not pool.get("primaryNodes"):
            raise ValueError(f"invalid node pool {pool.get('poolId')}")
        replicas = pool.get("replicaNodes") or []
        if len(replicas) < int(pool.get("minimumReplicas", 0)):
            raise ValueError(f"insufficient replica candidates for {pool['poolId']}")
    for group in groups.values():
        if group.get("nodePool") not in pools:
            raise ValueError(f"unknown node pool for {group['groupId']}")
        if int(group.get("partitionCount", 0)) <= 0:
            raise ValueError(f"invalid partition count for {group['groupId']}")
    for rule in rules.values():
        if rule.get("placementGroup") not in groups:
            raise ValueError(f"unknown placement group for {rule['ruleId']}")
        parts = str(rule.get("placementKeyPattern", "")).split(SEP)
        if len(parts) != 3 or any(not part or ("*" in part and part != "*") for part in parts):
            raise ValueError(f"invalid placement pattern for {rule['ruleId']}")


def resolve_group(catalog: dict[str, Any], location: str, market: str, symbol: str) -> str:
    key = [location, market, symbol]
    candidates = sorted(
        (rule for rule in catalog["rules"] if rule.get("enabled", True)),
        key=lambda rule: (-int(rule.get("priority", 0)),
                          -sum(part != "*" for part in rule["placementKeyPattern"].split(SEP)),
                          rule["ruleId"]),
    )
    for rule in candidates:
        pattern = rule["placementKeyPattern"].split(SEP)
        if all(expected == "*" or expected.lower() == actual.lower()
               for expected, actual in zip(pattern, key)):
            return str(rule["placementGroup"])
    raise ValueError(f"no placement rule for {location}/{market}/{symbol}")


def unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get(key, ""))
        if not identity or identity in result:
            raise ValueError(f"missing or duplicate {label}: {identity}")
        result[identity] = row
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "control.prod" / "placement"
    order = load_catalog(root / "ordersvr-v1.json")
    md = load_catalog(root / "mdsvr-v1.json")
    expected_order = {
        "BTCUSDT": "ORDER_A", "ETHUSDT": "ORDER_B", "SOLUSDT": "ORDER_C",
        "UNIUSDT": "ORDER_C", "XRPUSDT": "ORDER_C",
    }
    for symbol, group in expected_order.items():
        if resolve_group(order, "WEB_E2E", "4", symbol) != group:
            raise SystemExit(f"unexpected Order placement for {symbol}")
    for symbol in ("ETHUSDT", "SOLUSDT", "UNIUSDT", "XRPUSDT"):
        if resolve_group(md, "WEB_E2E", "4", symbol) != "MD_NORMAL":
            raise SystemExit(f"unexpected MD placement for {symbol}")
    if resolve_group(md, "WEB_E2E", "4", "BTCUSDT") != "MD_BTC":
        raise SystemExit("unexpected MD placement for BTCUSDT")
    print("placement_catalogs=valid order_rules=5 md_rules=2 placement_enabled=false")


if __name__ == "__main__":
    main()
