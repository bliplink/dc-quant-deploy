#!/usr/bin/env python3
"""Read-only multitenant load-ramp readiness gate for the current SaaS demo.

Does NOT register tenants, change Robot settings, submit orders, or infer
matched-order TPS from ClickHouse's non-authoritative market-trade rows.
A PASS is only a prerequisite to plan a controlled next load stage, never
proof of 50/100/200-tenant capacity or HA correctness.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import re
import subprocess
import sys

SERVICES = (
    "dc-saas-robotsvr", "dc-saas-ordersvr", "dc-saas-ordersvr-b",
    "dc-saas-ordersvr-c", "dc-saas-mdsvr", "dc-saas-gateway",
    "dc-saas-projectionsvr", "dc-saas-mysql", "dc-saas-clickhouse",
)
READ_ONLY_METHODS = (
    "inspect", "exec", "stats",
)
CPU_PSI_PATTERN = re.compile(r"^some\s+avg10=([0-9]+(?:\.[0-9]+)?)\b")
QUANTITY_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(B|KiB|MiB|GiB|TiB)$")
UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}


def capacity_bytes(text):
    match = QUANTITY_PATTERN.match(text.strip())
    if not match:
        raise ValueError("invalid Docker memory unit")
    return float(match.group(1)) * UNITS[match.group(2)]


def memory_percent(text):
    pieces = text.split("/")
    if len(pieces) != 2:
        raise ValueError("invalid Docker stats memory value")
    limit = capacity_bytes(pieces[1])
    if limit <= 0:
        raise ValueError("Docker memory limit must be nonzero")
    return round(100 * capacity_bytes(pieces[0]) / limit, 2)


def market_rows(raw):
    rows = []
    for line in raw.splitlines():
        cols = line.split("\t")
        if len(cols) != 3:
            raise ValueError("invalid ClickHouse location market-activity row")
        location, num, idle = cols
        if not re.fullmatch(r"[A-Z0-9]{4,16}", location):
            raise ValueError("invalid tenant location")
        if not num.isdecimal() or not idle.isdecimal():
            raise ValueError("invalid event count / idle age")
        rows.append({"location": location, "events5m": int(num), "idleSeconds": int(idle)})
    if not rows or len({x["location"] for x in rows}) != len(rows):
        raise ValueError("no tenant activity or duplicate locations")
    return rows


def evaluate(rows, cpu_psi, order_mem_pct, robot_cpu_pct,
             min_tenants=10, min_events=2, max_cpu_psi=25.0,
             max_inactive_pct=20.0, max_order_mem=80.0, max_robot_cpu=85.0):
    if any(not math.isfinite(float(x)) or float(x) < 0
           for x in (cpu_psi, order_mem_pct, robot_cpu_pct)):
        raise ValueError("invalid resource metric")
    inactive = [r["location"] for r in rows if r["events5m"] < min_events]
    idle_count = len(inactive)
    inactivity_pct = round(100.0 * idle_count / len(rows), 2)
    reasons = []
    if len(rows) < min_tenants:
        reasons.append(f"TOO_FEW_OBSERVED_TENANTS:{len(rows)}<{min_tenants}")
    if inactivity_pct > max_inactive_pct:
        reasons.append(f"MARKET_TRADES_INACTIVE:{idle_count}/{len(rows)}")
    if float(cpu_psi) > max_cpu_psi:
        reasons.append(f"CPU_PSI_HIGH:{cpu_psi:.2f}>{max_cpu_psi:.2f}")
    if float(order_mem_pct) > max_order_mem:
        reasons.append(f"ORDER_B_MEMORY_HIGH:{order_mem_pct:.2f}>{max_order_mem:.2f}")
    if float(robot_cpu_pct) > max_robot_cpu:
        reasons.append(f"ROBOT_CPU_HIGH:{robot_cpu_pct:.2f}>{max_robot_cpu:.2f}")
    return {
        "gate": "NOT_READY" if reasons else "BASELINE_READY_ONLY",
        "nextRampAuthorized": False,  # An operator must separately review/authorize load.
        "reasons": reasons,
        "tenantLocations": len(rows),
        "marketRowsLast300Seconds": sum(r["events5m"] for r in rows),
        "marketRowsPerSecondNotOrderTPS": round(sum(r["events5m"] for r in rows)/300.0, 5),
        "inactiveTenants": inactive,
        "inactivePercent": inactivity_pct,
        "cpuPsiSomeAvg10Percent": float(cpu_psi),
        "orderBMemoryPercent": float(order_mem_pct),
        "robotCpuDockerPercent": float(robot_cpu_pct),
        "warning": "Market data rows are not authoritative order TPS or a capacity guarantee.",
    }


def docker(*args):
    if args[0] not in READ_ONLY_METHODS:
        raise ValueError("only Docker read-only methods allowed")
    result = subprocess.run(("docker",) + args, text=True, capture_output=True,
                            timeout=25, check=True)
    return result.stdout.strip()


def collect():
    for name in SERVICES:
        state = docker("inspect", "-f", "{{.State.Running}}|{{.State.OOMKilled}}", name)
        if state != "true|false":
            raise ValueError(f"required service not healthy: {name}")
    pressure = docker("exec", "dc-saas-ordersvr", "cat", "/proc/pressure/cpu")
    match = next((CPU_PSI_PATTERN.match(s) for s in pressure.splitlines()
                  if CPU_PSI_PATTERN.match(s)), None)
    if not match:
        raise ValueError("CPU PSI avg10 unavailable")
    raw = docker("exec", "dc-saas-clickhouse", "clickhouse-client", "--query",
        "SELECT location, countIf(createTime > now() - INTERVAL 300 SECOND), "
        "dateDiff('second', max(createTime), now()) "
        "FROM dc.market_trade GROUP BY location ORDER BY location FORMAT TabSeparatedRaw")
    stats = docker("stats", "--no-stream", "--format",
                   "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}",
                   "dc-saas-robotsvr", "dc-saas-ordersvr-b")
    measurements = {}
    for line in stats.splitlines():
        cols = line.split("|", 2)
        if len(cols) != 3:
            raise ValueError("invalid Docker stats row")
        measurements[cols[0]] = {"cpu": float(cols[1].rstrip("%")),
                                  "memoryPct": memory_percent(cols[2])}
    if set(measurements) != {"dc-saas-robotsvr", "dc-saas-ordersvr-b"}:
        raise ValueError("Docker stats missing critical containers")
    return market_rows(raw), float(match.group(1)), (
        measurements["dc-saas-ordersvr-b"]["memoryPct"],
        measurements["dc-saas-robotsvr"]["cpu"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Optional JSON artifact location")
    args = parser.parse_args()
    try:
        rows, psi, (mem, cpu) = collect()
        result = evaluate(rows, psi, mem, cpu)
    except (OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as error:
        result = {"gate": "NOT_READY", "nextRampAuthorized": False,
                  "reasons": ["TELEMETRY_UNAVAILABLE"],
                  "errorType": type(error).__name__}
    result["checkedAtUtc"] = datetime.now(timezone.utc).isoformat()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        from pathlib import Path
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 2 if result["gate"] == "NOT_READY" else 0


if __name__ == "__main__":
    sys.exit(main())
