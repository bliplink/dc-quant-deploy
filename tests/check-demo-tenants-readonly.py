#!/usr/bin/env python3
"""Read-only 10-tenant SaaS Demo audit: robots, public order books and resources."""
import importlib.util
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("trial_e2e_readonly", HERE / "run-auto-tenant-trading-e2e.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)

EXPECTED = int(os.environ.get("DEMO_TENANT_EXPECT", "10"))
OUTPUT = Path(os.environ["DEMO_TENANT_AUDIT_OUTPUT"])
results = {"timestampUtc": datetime.now(timezone.utc).isoformat(), "expectedTenants": EXPECTED}
errors = []

def sql(query):
    return trial.sql(query)

def check():
    if EXPECTED < 1 or EXPECTED > 200:
        raise ValueError("invalid expected tenant count")
    tenants = sql("SELECT location,status FROM dc_tenant WHERE status IN ('ACTIVE','TRIAL') ORDER BY location")
    results["observedTenants"] = len(tenants)
    if len(tenants) != EXPECTED:
        errors.append("TENANT_COUNT_%s_EXPECTED_%s" % (len(tenants), EXPECTED))
    all_robots = sql("SELECT location,runtime_status,open_order_count,enabled "
                     "FROM dc_tenant_robot ORDER BY location")
    by_location = {row[0]: row for row in all_robots}
    inspections = []
    for location, status in tenants:
        item = {"location": location, "tenantStatus": status}
        if not re.fullmatch("[A-Z0-9]{4,16}", location):
            errors.append("UNSAFE_TENANT_LOCATION")
            continue
        robot = by_location.get(location)
        item["robot"] = None if robot is None else {
            "status": robot[1], "openOrders": int(robot[2]), "enabled": robot[3]
        }
        if robot is None or robot[1] != "RUNNING" or robot[2] != "40" or robot[3] != "1":
            errors.append("ROBOT_NOT_READY_" + location)
        trial.LOCATION = location
        try:
            bids, asks = trial.market_book()
            item["publicBook"] = {
                "bidLevels": len(bids), "askLevels": len(asks),
                "bestBid": str(max(bids)) if bids else None,
                "bestAsk": str(min(asks)) if asks else None,
            }
            if len(bids) != 10 or len(asks) != 10 or max(bids) >= min(asks):
                errors.append("MARKET_BOOK_INVALID_" + location)
        except Exception as exc:
            item["marketError"] = str(exc)[:150]
            errors.append("MARKET_UNAVAILABLE_" + location)
        inspections.append(item)
        print("[tenant-audit] %s robot=%s orders=%s market=%s" % (
            location, item["robot"]["status"] if item["robot"] else "MISSING",
            item["robot"]["openOrders"] if item["robot"] else 0,
            item.get("publicBook", {}).get("bidLevels", "-")), flush=True)
    results["tenants"] = inspections
    stats = subprocess.run(
        ["docker","stats","--no-stream","--format","{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}",
         "dc-saas-robotsvr","dc-saas-ordersvr","dc-saas-ordersvr-b",
         "dc-saas-ordersvr-c","dc-saas-tradesvr","dc-saas-tradesvr-b",
         "dc-saas-projectionsvr"],
        text=True,capture_output=True,check=True,timeout=35)
    results["resourceSnapshot"] = [
        dict(zip(("name","cpu","memory"), row.split("|"))) for row in stats.stdout.splitlines()
    ]
    results["errors"] = errors
    results["status"] = "PASS_10_TENANT_SNAPSHOT" if not errors else "FAIL"
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
    print("[tenant-audit] %s evidence=%s" % (results["status"], OUTPUT),flush=True)
    return 0 if not errors else 1

if __name__ == "__main__":
    try:
        sys.exit(check())
    except Exception as exc:
        print("[tenant-audit] FAIL: %s" % exc, file=sys.stderr)
        sys.exit(2)
