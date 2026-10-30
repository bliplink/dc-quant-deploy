#!/usr/bin/env python3
"""T324 read-only barrier before replacing formal Demo Order/Trade.
No Docker access, no network calls, no data deletion. Does not release an image.
Run from the dc-quant-deploy repo: python3 tests/t324_restore_preflight.py
"""
from __future__ import annotations

from pathlib import Path
import os
import re

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / ".env.prod"
T319 = Path.home() / ".opentradingcore" / "t319-business-ready-20261030"


def env_values(file: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in file.read_text().splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if re.fullmatch(r"[A-Z0-9_]+", key):
            result[key] = val.strip().strip('"').strip("'")
    return result


def properties(file: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in file.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def main() -> int:
    if not ENV.is_file():
        print("T324_NO_GO: formal .env.prod not present")
        return 2
    data = env_values(ENV)
    issues: list[str] = []
    order_img = f"{data.get('ORDERSVR_IMAGE_REPOSITORY','')}:{data.get('ORDERSVR_TAG','')}"
    trade_img = f"{data.get('TRADESVR_IMAGE_REPOSITORY','')}:{data.get('TRADESVR_TAG','')}"
    if order_img != "local/otc-t319-ordersvr:virgin-e2-replica":
        issues.append("formal Order image is not T319/Common candidate; immutable verified image selection required")
    if trade_img != "local/otc-t319-tradesvr:virgin-e2-replica":
        issues.append("formal Trade image is not T319/Common candidate; immutable verified image selection required")
    if data.get("ORDER_CLUSTER_ENABLED") != "true":
        issues.append("formal Order A/B topology not enabled")
    if data.get("TRADE_CLUSTER_ENABLED") != "true":
        issues.append("formal Trade A/B topology not enabled")

    for service, typ in (("order", "Order"), ("trade", "Trade")):
        for node in ("A", "B"):
            file = T319 / service / node / "application.v4.properties"
            if not file.is_file():
                issues.append(f"missing original T319 candidate configuration {service}/{node}")
                continue
            p = properties(file)
            base = f"{service}.common"
            if p.get(base + ".gatewayDiscovery.enabled") != "true":
                issues.append(f"{service}/{node} has gatewayDiscovery disabled: cannot serve formal Gateway")
            zk = p.get(base + ".control.zkHosts", "")
            if "otc-t84-" in zk:
                issues.append(f"{service}/{node} uses isolated T84 bridge ZooKeeper DNS, not formal host-network registry")
            if "t318-virgin-" in p.get(base + ".control.manifestPath", ""):
                issues.append(f"{service}/{node} uses T318 isolated signed manifest, not a fresh formal Demo genesis")
            if "t319-ready-" in p.get(base + ".nodeRuntime.dataRoot", ""):
                issues.append(f"{service}/{node} WAL root is T319 isolated, not fresh authoritative formal data")
            if not re.fullmatch(r"\d+", p.get(base + ".nodeRuntime.bindPort", "")):
                issues.append(f"{service}/{node} has no validated Common Netty bindPort")

    for part in ("order", "trade"):
        isolated_db = T319 / "mysql" / "DBPoolConfig.ini"
        if not isolated_db.is_file():
            issues.append(f"{part} independent isolated test DB config missing")

    # Formal Compose uses host networking. T321 validated only with a separate
    # user-defined bridge and independent MySQL. Reusing the original container
    # and attaching formal ports does not prove authenticated READY or matching
    # committed WAL state.
    issues.append("T321 was validated in bridge networking with isolated MySQL; formal host-network + Gateway E2E not validated")
    print("T324_RESTORE_ORDER_TRADE_READ_ONLY_PREFLIGHT")
    print("candidate_order_and_trade=Spring_boot_only")
    print("original_signed_WAL_and_RSA=UNCHANGED")
    print("formal_Demo_data=UNCHANGED")
    if issues:
        for i, reason in enumerate(issues, 1):
            print(f"BLOCKER_{i:02d}: {reason}")
        print("T324_NO_GO: DO NOT replace formal containers with T321 test image/config unchanged")
        print("NEXT: bootstrap new valid Common genesis in formal runtime, build Gateway-enabled paired images, then run actual trade E2E")
        return 2
    print("T324_STATIC_PREFLIGHT_PASS: still requires live Docker/config/transaction validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
