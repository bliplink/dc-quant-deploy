#!/usr/bin/env python3
"""Read-only Mac Demo check: Admin trial worker, Robot identity, live BBO, Binance source.

This is NOT a substitute for placing real orders, Tape trades, or HA acceptance.
No user credentials, API secrets, or SQL row payloads are printed.
"""
import argparse
import json
import re
import subprocess
from urllib.parse import urlparse

CONTAINER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SQL = """SELECT 'bootstrap_total',COUNT(*) FROM dc_tenant_liquidity_bootstrap;
SELECT 'bootstrap_complete',COUNT(*) FROM dc_tenant_liquidity_bootstrap WHERE status='COMPLETE';
SELECT 'robot_enabled',COUNT(*) FROM dc_tenant_robot WHERE enabled=1;
SELECT 'robot_live',COUNT(*) FROM dc_tenant_robot WHERE enabled=1 AND
 runtime_status='RUNNING' AND open_order_count>=2 AND
 last_heartbeat_time>=DATE_SUB(NOW(),INTERVAL 30 SECOND);
SELECT 'robot_stale',COUNT(*) FROM dc_tenant_robot WHERE enabled=1 AND
 runtime_status='STALE';
"""


def run(cmd, stdin=None, timeout=20):
    result = subprocess.run(cmd, input=stdin, text=True, capture_output=True,
                            check=False, timeout=timeout)
    if result.returncode:
        raise RuntimeError("RUNTIME_READ_FAILURE")
    return result.stdout


def inspect(name):
    if not CONTAINER_NAME.fullmatch(name):
        raise ValueError("INVALID_CONTAINER_NAME")
    response = json.loads(run(["docker", "inspect", name]))
    if len(response) != 1:
        raise RuntimeError("CONTAINER_NOT_FOUND")
    item = response[0]
    values = dict(s.split("=", 1) for s in item.get("Config", {}).get("Env", []) if "=" in s)
    return {"running": bool(item.get("State", {}).get("Running")), "env": values}


def mysql_counts(name):
    if not CONTAINER_NAME.fullmatch(name):
        raise ValueError("INVALID_MYSQL_CONTAINER")
    # Password is used INSIDE the MySQL container, never in host argv/output.
    output = run(["docker", "exec", "-i", name, "sh", "-c",
                  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N dc'],
                 stdin=SQL)
    counts = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] in (
                "bootstrap_total", "bootstrap_complete", "robot_enabled",
                "robot_live", "robot_stale"):
            counts[parts[0]] = int(parts[1])
    if len(counts) != 5:
        raise RuntimeError("ROBOT_SQL_CENSUS_INCOMPLETE")
    return counts


def binance_flag(name):
    if not CONTAINER_NAME.fullmatch(name):
        raise ValueError("INVALID_APS_CONTAINER")
    config = run(["docker", "exec", name, "sh", "-c",
                  "grep -m1 '^enableBinanceFlag=' "
                  "/srv/dc/dc/APSSvr/config/application.properties"])
    return config.strip() == "enableBinanceFlag=true"


def binance_dns_error(name):
    if not CONTAINER_NAME.fullmatch(name):
        raise ValueError("INVALID_APS_CONTAINER")
    result = subprocess.run(["docker", "logs", "--tail", "3000", name],
                            capture_output=True, text=True, timeout=18)
    if result.returncode:
        raise RuntimeError("APSSVR_LOG_READ_FAILURE")
    return "UnknownHostException: fstream.binance.com" in (result.stdout + result.stderr)


def assess(admin, robot, aps, stats, enabled, dns_error):
    problems = []
    a, r = admin["env"], robot["env"]
    if not admin["running"] or a.get("TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED") != "true":
        problems.append("TRIAL_WORKER_NOT_RUNNING")
    if not a.get("TRIAL_LIQUIDITY_MASTER_KEY"):
        problems.append("TRIAL_BOOTSTRAP_MASTER_KEY_MISSING")
    if not robot["running"]:
        problems.append("ROBOT_SERVICE_NOT_RUNNING")
    if not r.get("ROBOT_GATEWAY_USER") or r.get("ROBOT_GATEWAY_USER") != r.get("ROBOT_RUNTIME_USER_ID"):
        problems.append("ROBOT_GATEWAY_USER_MISMATCH")
    if not r.get("ROBOT_RUNTIME_API_KEY") or not r.get("ROBOT_RUNTIME_API_SECRET") or \
            r.get("ROBOT_GATEWAY_PASSWORD") != r.get("ROBOT_RUNTIME_API_SECRET"):
        problems.append("ROBOT_GATEWAY_CREDENTIALS_MISSING_OR_MISMATCH")
    admin_url = urlparse(a.get("TRIAL_LIQUIDITY_GATEWAY_URL", ""))
    robot_url = urlparse(r.get("GATEWAY_HTTP_URL", ""))
    if admin_url.hostname != "127.0.0.1" or admin_url.port != robot_url.port:
        problems.append("TRIAL_GATEWAY_PORT_MISMATCH")
    if not aps["running"] or not enabled:
        problems.append("BINANCE_SOURCE_DISABLED_OR_NOT_RUNNING")
    if dns_error:
        problems.append("BINANCE_DNS_UNAVAILABLE")
    if stats["bootstrap_total"] == 0:
        problems.append("NO_TRIAL_BOOTSTRAP_JOBS")
    if stats["robot_enabled"] == 0:
        problems.append("NO_ENABLED_ROBOT_TASKS")
    if stats["robot_live"] == 0:
        problems.append("NO_LIVE_TWO_SIDED_QUOTES")
    return sorted(set(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ("admin", "robot", "aps", "mysql"):
        parser.add_argument("--" + role, required=True)
    args = parser.parse_args()
    try:
        admin, robot, aps = (inspect(args.admin), inspect(args.robot), inspect(args.aps))
        stats = mysql_counts(args.mysql)
        problems = assess(admin, robot, aps, stats, binance_flag(args.aps),
                          binance_dns_error(args.aps))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "NO_GO", "reasons": ["RUNTIME_CENSUS_UNAVAILABLE"]}))
        raise SystemExit(2)
    print(json.dumps({
        "status": "NO_GO" if problems else "PREFLIGHT_PASS_NOT_E2E",
        "bootstrap_jobs": stats["bootstrap_total"],
        "completed_bootstrap_jobs": stats["bootstrap_complete"],
        "enabled_robots": stats["robot_enabled"],
        "live_two_sided_robots": stats["robot_live"],
        "stale_robots": stats["robot_stale"],
        "reasons": problems,
        "real_trades_verified": False,
        "tape_trades_verified": False,
    }, sort_keys=True))
    if problems:
        raise SystemExit(2)


if __name__ == "__main__":
    main()