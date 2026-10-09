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


def collect_order_gc():
    """Read only live Order B HotSpot counters, no JVM attach or signals."""
    import importlib.util
    from pathlib import Path
    import time
    script = Path(__file__).resolve().parents[1] / "scripts/observe-order-jvm-gc.py"
    spec = importlib.util.spec_from_file_location("safe_order_gc_counters", script)
    if spec is None or spec.loader is None:
        raise ValueError("Order GC observer not available")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    initial = module.read_node("dc-saas-ordersvr-b")
    time.sleep(3)
    final = module.read_node("dc-saas-ordersvr-b")
    delta = module.interval(initial, final)
    old = module.old_generation_capacity(final)
    old_max = module.old_generation_max_capacity(final)
    if old is None or old_max is None:
        raise ValueError("Order B old-generation usage / max capacity is unavailable")
    return {"fullGCsIn3Seconds": delta["full_count"],
            "fullGCmsIn3Seconds": round(delta["full_ticks"], 1),
            "oldGenerationCommittedPercent": round(old[2], 2),
            "oldGenerationMaxPercent": round(old_max[2], 2),
            "oldGenerationUsedMiB": round(old[0], 1),
            "oldGenerationMaxMiB": round(old_max[1], 1)}


def parse_enabled_robot_rows(raw):
    """Parse safe, credential-free records from the running MySQL container."""
    results = []
    for line in raw.splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            raise ValueError("invalid enabled Robot status row")
        location, robot_id, status, count, heartbeat_age = fields
        if (not re.fullmatch(r"[A-Z0-9]{4,16}", location)
                or not robot_id or len(robot_id) > 64
                or not count.isdecimal()):
            raise ValueError("invalid enabled Robot identity/quote count")
        try:
            age = int(heartbeat_age)
        except ValueError as e:
            raise ValueError("invalid Robot heartbeat age") from e
        if age < -1:
            raise ValueError("invalid Robot heartbeat age")
        results.append({"location": location, "robotId": robot_id,
                        "status": status, "openOrders": int(count),
                        "heartbeatAgeSeconds": age})
    if not results or len({(r["location"], r["robotId"]) for r in results}) != len(results):
        raise ValueError("missing or duplicate enabled Robots")
    return results


def collect_enabled_robots():
    # The sensitive root password stays INSIDE the mysql container, never
    # expanded into host argv, logs or a shell command on the Mac.
    sql = (
        "SELECT location,robot_id,runtime_status,open_order_count,"
        "COALESCE(TIMESTAMPDIFF(SECOND,"
        "STR_TO_DATE(LEFT(last_heartbeat_time,19),'%Y-%m-%d %H:%i:%s'),"
        "NOW()),-1) FROM dc.dc_tenant_robot WHERE enabled=1 ORDER BY location,robot_id"
    )
    import shlex
    statement = ('MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --batch '
                 '--raw --skip-column-names -e ' + shlex.quote(sql))
    result = docker("exec", "dc-saas-mysql", "sh", "-c", statement)
    return parse_enabled_robot_rows(result)



ORDER_RECOVERY_FAILED = re.compile(r"ORDER_PARTITION_RECOVERY_FAILED\s+node:(OrderSvr[A-C]),\s*partition:(P\d{3})")
ORDER_NOT_READY = re.compile(r"PARTITION_NOT_READY[^\n]*partition=(P\d{3})")
ORDER_NODES = ("dc-saas-ordersvr", "dc-saas-ordersvr-b", "dc-saas-ordersvr-c")


def parse_partition_recovery_signals(raw, node):
    """Summarize error evidence only; never surface order/session log content."""
    recovery = {}
    rejected = {}
    for line in raw.splitlines():
        failure = ORDER_RECOVERY_FAILED.search(line)
        denied = ORDER_NOT_READY.search(line)
        if failure:
            partition = failure.group(2)
            recovery[partition] = recovery.get(partition, 0) + 1
        if denied:
            partition = denied.group(1)
            rejected[partition] = rejected.get(partition, 0) + 1
    return [{"node": node, "partition": location,
             "recoveryFailures": recovery.get(location, 0),
             "notReadyRejections": rejected.get(location, 0)}
            for location in sorted(set(recovery) | set(rejected))]


def collect_partition_recovery_signals():
    signals = []
    for node in ORDER_NODES:
        result = subprocess.run(["docker", "logs", "--since", "180s", node],
                                text=True, capture_output=True,
                                timeout=30, check=True)
        signals.extend(parse_partition_recovery_signals(
            result.stdout + "\n" + result.stderr, node))
    return signals


def evaluate(rows, cpu_psi, order_mem_pct, robot_cpu_pct,
             min_tenants=10, min_events=2, max_cpu_psi=25.0,
             max_inactive_pct=20.0, max_order_mem=80.0, max_robot_cpu=85.0,
             order_gc=None, max_old_gen_percent=95.0,
             robot_cpu_quota_cores=1.0, enabled_robots=None,
             heartbeat_fresh_seconds=45, partition_signals=None):
    if any(not math.isfinite(float(x)) or float(x) < 0
           for x in (cpu_psi, order_mem_pct, robot_cpu_pct, robot_cpu_quota_cores)):
        raise ValueError("invalid resource metric")
    if robot_cpu_quota_cores <= 0:
        raise ValueError("robot CPU quota is invalid")
    robot_quota_util_pct = float(robot_cpu_pct) / robot_cpu_quota_cores

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
    if robot_quota_util_pct > max_robot_cpu:
        reasons.append(f"ROBOT_CPU_QUOTA_UTIL_HIGH:{robot_quota_util_pct:.2f}>{max_robot_cpu:.2f}")
    invalid_robots = []
    if not isinstance(enabled_robots, list) or not enabled_robots:
        reasons.append("ENABLED_ROBOT_TELEMETRY_MISSING")
    else:
        observed_robot_tenants = {r["location"] for r in enabled_robots}
        if len(observed_robot_tenants) < min_tenants:
            reasons.append(f"TOO_FEW_ENABLED_ROBOT_TENANTS:{len(observed_robot_tenants)}<{min_tenants}")
        for robot in enabled_robots:
            if (robot["status"] != "RUNNING"
                    or robot["openOrders"] <= 0
                    or robot["heartbeatAgeSeconds"] < 0
                    or robot["heartbeatAgeSeconds"] > heartbeat_fresh_seconds):
                invalid_robots.append({
                    "location": robot["location"],
                    "robotId": robot["robotId"],
                    "status": robot["status"],
                    "openOrders": robot["openOrders"],
                    "heartbeatAgeSeconds": robot["heartbeatAgeSeconds"],
                })
        if invalid_robots:
            reasons.append(f"ENABLED_ROBOTS_UNHEALTHY:{len(invalid_robots)}/{len(enabled_robots)}")
    if partition_signals is None:
        reasons.append("ORDER_PARTITION_RECOVERY_TELEMETRY_MISSING")
    elif partition_signals:
        affected = sorted({item["partition"] for item in partition_signals})
        reasons.append("ORDER_PARTITIONS_UNREADY:" + ",".join(affected))
    if not isinstance(order_gc, dict):
        reasons.append("ORDER_B_GC_TELEMETRY_MISSING")
    else:
        full_gc = order_gc.get("fullGCsIn3Seconds")
        old_pct = order_gc.get("oldGenerationMaxPercent")
        if (not isinstance(full_gc, int) or full_gc < 0
                or not isinstance(old_pct, (float, int))
                or not math.isfinite(old_pct) or not 0 <= old_pct <= 100):
            reasons.append("ORDER_B_GC_TELEMETRY_INVALID")
        else:
            if full_gc > 0:
                reasons.append(f"ORDER_B_FULL_GC:{full_gc}/3s")
            if old_pct > max_old_gen_percent:
                reasons.append(f"ORDER_B_OLD_GEN_MAX_HIGH:{old_pct:.2f}>{max_old_gen_percent:.2f}")

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
        "robotCpuQuotaCores": robot_cpu_quota_cores,
        "robotCpuQuotaUtilizationPercent": round(robot_quota_util_pct, 2),
        "enabledRobotsObserved": len(enabled_robots) if isinstance(enabled_robots, list) else 0,
        "enabledRobotsUnhealthy": invalid_robots,        "orderPartitionRecoverySignalsLast180s": partition_signals,

        "orderBHotSpotGC": order_gc,
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
    robot_cpu_nanos = int(docker("inspect", "-f", "{{.HostConfig.NanoCpus}}",
                                  "dc-saas-robotsvr"))
    if robot_cpu_nanos <= 0:
        raise ValueError("cannot measure Robot CPU quota utilization")
    return market_rows(raw), float(match.group(1)), (
        measurements["dc-saas-ordersvr-b"]["memoryPct"],
        measurements["dc-saas-robotsvr"]["cpu"]), collect_order_gc(), (
            robot_cpu_nanos / 1_000_000_000.0), collect_enabled_robots(), collect_partition_recovery_signals()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Optional JSON artifact location")
    args = parser.parse_args()
    try:
        rows, psi, (mem, cpu), gc, quota, enabled_robots, partition_signals = collect()
        result = evaluate(rows, psi, mem, cpu, order_gc=gc,
                          robot_cpu_quota_cores=quota, enabled_robots=enabled_robots,
                          partition_signals=partition_signals)
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
