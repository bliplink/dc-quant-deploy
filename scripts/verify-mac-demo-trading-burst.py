#!/usr/bin/env python3
"""Run a measured burst through authenticated Demo clients and an optional voter fault."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
import json
from pathlib import Path
import re
import runpy
import secrets
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
CAPACITY = runpy.run_path(str(HERE / "verify-mac-demo-robot-capacity.py"))
PRODUCT = CAPACITY["PRODUCT"]
MEASURE = CAPACITY["MEASURE"]
ENDPOINT = "http://127.0.0.1:49502/httpapi/"


def new_trader(location, run, number):
    username = f"burst_{run}_{number}"
    password = secrets.token_urlsafe(24)
    user = PRODUCT["ok"](ENDPOINT, "AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "location": location, "username": username, "name": "T554 Demo burst",
        "email": username + "@acceptance.invalid", "password": password, "request_id": username, "cid": username,
    })["user_id"]
    token = PRODUCT["ok"](ENDPOINT, "LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": username, "user_id": user, "user_name": username, "password": password,
        "client_type": "WEB", "Location": location,
    })["token"]
    PRODUCT["ok"](ENDPOINT, "TradeSvr", "setLeverage", {
        "userID": user, "securityID": "BTCUSDT", "location": location, "leverage": 10,
    }, token)
    PRODUCT["ok"](ENDPOINT, "TradeSvr", "cashIn", {
        "Amount": "5000", "UserID": user, "Location": location, "Demo": "0", "Info1": username,
    }, token)
    return location, user, token


def crossing_price(book, buy):
    side = "1" if buy else "0"
    prices = [Decimal(row["MDEntryPx"]) for row in book if row["MDEntryType"] == side]
    return min(prices) if buy else max(prices)


def send(trader, run, sequence, buy):
    location, user, token = trader
    client_id = f"T554BURST-{run}-{sequence}"
    try:
        market = PRODUCT["ok"](ENDPOINT, "MDSvr", "queryPublicMarket", {
            "location": location, "securityID": "BTCUSDT",
        })
        price = crossing_price(market["orderBook"]["NoMDEntries"], buy)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, DecimalException):
        return None, "MARKET_UNAVAILABLE", None
    started = time.monotonic()
    try:
        reply = PRODUCT["call"](ENDPOINT, "OrderSvr", "placeOrder", {
            "OCType": "OPEN", "OrderQty": "0.0001", "OrdType": "Limit", "ClOrdID": client_id,
            "Terminal": "API", "AlgoName": "cross", "Side": "Buy" if buy else "Sell",
            "Price": format(price, "f"), "UserID": user, "MarketIndicator": "4",
            "TimeInForce": "IOC", "SecurityID": "BTCUSDT", "Location": location, "Demo": "0",
        }, token, timeout=8)
        code = str(reply.get("code", "UNKNOWN"))
    except (OSError, ValueError):
        code = "NO_RESPONSE"
    return client_id, code, round((time.monotonic() - started) * 1000, 3)


def reconcile(run, responses):
    rows = PRODUCT["readonly_sql"](
        "SELECT o.clord_id,o.order_id,o.ord_status,COUNT(DISTINCT e.exec_id) FROM dc_orders o "
        "LEFT JOIN dc_orders_execorders e ON e.location=o.location AND e.order_id=o.order_id "
        f"WHERE o.clord_id LIKE 'T554BURST-{run}-%' GROUP BY o.clord_id,o.order_id,o.ord_status")
    accepted = {client for client, code, _ in responses if client and code == "0"}
    observed = {client for client, _, _, _ in rows}
    filled = sum(int(executions) for _, _, status, executions in rows if status in {"Filled", "Partially_Filled"})
    return {"acknowledged": len(accepted), "sql_orders": len(observed), "sql_filled_executions": filled,
            "acknowledged_missing_from_sql": sorted(accepted - observed), "duplicate_sql_orders": len(rows) - len(observed)}


def fault_evidence(root, log, fault, since, until):
    service, slot = fault.split("-")
    prefix = f"[mac-demo HA] {service.title()}Svr{slot}: complete; "
    matches = [Path(line[len(prefix):]) for line in log.read_text().splitlines() if line.startswith(prefix)]
    if len(matches) != 1 or matches[0].parent != root:
        return None
    path = matches[0] / "evidence.json"
    record = json.loads(path.read_text())
    if (record["generation"] != root.name or record["fault"] != "kill" or record["old_exit_code"] != 137
            or record["status"] != "COMMON_PHYSICAL_AND_ROBOT_TRAFFIC_PASS"):
        return None
    stopped = MEASURE["at"](record["old_finished_at"])
    return {"evidence": str(path), "old_finished_at": stopped.isoformat(),
            "fault_inside_load_window": since <= stopped < until,
            "first_certified_robot_route": record.get("robot_partition_local"),
            "full_local_at": record["robot_local_started_at"],
            "full_takeover_seconds": record["survivor_local_seconds"],
            "strict_home_seconds": record["strict_home_seconds"],
            "local_trade_commits_with_rpo_risk": len(record["robot_while_local"]["local_trade_commits"]),
            "robot_during_takeover": record["robot_during_takeover"],
            "robot_during_return": record["robot_during_return"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--factor", type=float, default=2.5)
    parser.add_argument("--fault", choices=("order-A", "order-B", "trade-A", "trade-B"))
    parser.add_argument("--cohort-offset", type=int, default=0)
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    baseline_path = args.baseline.resolve(strict=True)
    if (baseline_path.parent != root or not baseline_path.name.startswith("robot-steady-")
            or not 300 <= args.seconds <= 600 or not 2 <= args.factor <= 3
            or not 0 <= args.cohort_offset <= 188):
        parser.error("Use a passing steady report for the same generation, 300–600 seconds and a 2–3 factor")
    baseline = json.loads(baseline_path.read_text())
    CAPACITY["require_strict_demo"](root)
    if baseline.get("generation") != root.name or baseline.get("passed") is not True:
        raise RuntimeError("The steady Robot evidence must have passed in this exact generation")
    locations = [row[0] for row in PRODUCT["readonly_sql"](
        "SELECT approved_location FROM dc_tenant_application WHERE status='APPROVED' "
        "AND organization_name LIKE 'T554 Demo Capacity %' ORDER BY approved_location "
        f"LIMIT 12 OFFSET {args.cohort_offset}")]
    if not locations or any(not re.fullmatch(r"[A-Z0-9]{6}", loc) for loc in locations):
        raise RuntimeError("No dedicated Demo capacity tenants are available for the burst")
    interval = (datetime.fromisoformat(baseline["until"]) - datetime.fromisoformat(baseline["from"])).total_seconds()
    baseline_rate = (baseline["quote_requests"] + baseline["tape_requests"]) / interval
    extra_rate = (args.factor - 1) * baseline_rate
    if not 0 < extra_rate <= 100:
        raise RuntimeError("Measured baseline is outside this bounded Demo burst driver")
    run = secrets.token_hex(4)
    traders = [new_trader(loc, run, i) for i, loc in enumerate(locations)]
    root_report = root / f"burst-{run}"
    root_report.mkdir(mode=0o700)
    control_before = CAPACITY["require_strict_demo"](root)
    since = datetime.now(timezone.utc)
    begun = time.monotonic()
    pending, responses = set(), []
    dropped = 0
    fault = None
    with (root_report / "fault.log").open("x") as fault_log, ThreadPoolExecutor(max_workers=24) as clients, \
            MEASURE["sample_resources"](root.name) as resource_samples:
        for sequence in range(int(args.seconds * extra_rate)):
            scheduled = begun + sequence / extra_rate
            time.sleep(max(0, scheduled - time.monotonic()))
            elapsed = time.monotonic() - begun
            if elapsed >= args.seconds:
                break
            if args.fault and elapsed >= 60 and fault is None:
                service, slot = args.fault.split("-")
                fault = subprocess.Popen([sys.executable, str(HERE / "roll-mac-demo-voter.py"), str(root),
                                          service, slot, "--fault", "kill", "--robot-traffic", "--timeout", "3600"],
                                         stdout=fault_log, stderr=subprocess.STDOUT)
            finished = {future for future in pending if future.done()}
            responses.extend(future.result() for future in finished)
            pending.difference_update(finished)
            if len(pending) >= 24:
                dropped += 1
            else:
                buy = sequence // len(traders) % 2 == 0
                pending.add(clients.submit(send, traders[sequence % len(traders)], run, sequence, buy))
        responses.extend(future.result() for future in as_completed(pending))
        until = datetime.now(timezone.utc)
    robot = MEASURE["measure"](root.name, since, until, set(baseline["runtime_status"]))
    duration = (until - since).total_seconds()
    actual_rate = (robot["quote_requests"] + robot["tape_requests"]
                   + sum(client is not None for client, _, _ in responses)) / duration
    latencies = sorted(latency for _, _, latency in responses if latency is not None)
    fault_code = fault.wait(timeout=7200) if fault is not None else None
    physical_fault = fault_evidence(root, root_report / "fault.log", args.fault, since, until) if fault_code == 0 else None
    try:
        control_after = CAPACITY["require_strict_demo"](root)
        strict_after_burst = True
    except (RuntimeError, subprocess.SubprocessError):
        control_after = None
        strict_after_burst = False
    order_consistency = reconcile(run, responses)
    financial_code, financial_report, financial_checks = CAPACITY["reconcile_financial_cursor"]()
    summary = {"generation": root.name, "common_release": CAPACITY["common_release_identity"](root),
               "baseline_requests_per_second": baseline_rate,
               "observed_requests_per_second": actual_rate, "observed_factor": actual_rate / baseline_rate,
               "acknowledged_orders_per_second": order_consistency["acknowledged"] / duration,
               "funded_filled_executions_per_second": order_consistency["sql_filled_executions"] / duration,
               "http_order_latency_ms": {
                   "samples": len(latencies), "p50": MEASURE["percentile"](latencies, 0.5),
                   "p95": MEASURE["percentile"](latencies, 0.95),
                   "p99": MEASURE["percentile"](latencies, 0.99),
                   "p99_9": MEASURE["percentile"](latencies, 0.999)},
               "responses_by_code": dict(Counter(code for _, code, _ in responses)), "scheduler_drops": dropped,
               "robot": robot, "order_consistency": order_consistency, "fault": args.fault,
               "resource_samples": resource_samples,
               "control_generation_before": control_before, "control_generation_after": control_after,
               "fault_exit_code": fault_code, "physical_fault": physical_fault, "strict_after_burst": strict_after_burst,
               "financial_cursor": financial_report, "financial_cursor_checks": financial_checks}
    summary["passed"] = (strict_after_burst and 2 <= summary["observed_factor"] <= 3
                         and (args.fault or control_before == control_after)
                         and (not args.fault or physical_fault is not None and physical_fault["fault_inside_load_window"])
                         and any(point.get("containers") for point in resource_samples)
                         and order_consistency["sql_filled_executions"] > 0
                         and not order_consistency["acknowledged_missing_from_sql"]
                         and not order_consistency["duplicate_sql_orders"] and financial_code == 0)
    with (root_report / "summary.json").open("x") as out:
        json.dump(summary, out, indent=2)
        out.write("\n")
    print(f"{'PASS' if summary['passed'] else 'NO_GO'} {root_report}", flush=True)
    if not summary["passed"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
