#!/usr/bin/env python3
"""Read-only live business acceptance for Robot quoting, Tape IOC fills and Trade posting pairs.

PASS here does not certify Order/Trade A/B SIGKILL failover, physical ACKs or full HA.
Use exact running Docker containers and a bounded recent time window.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess

SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def require_container(value):
    if not SAFE.fullmatch(value):
        raise ValueError("INVALID_CONTAINER_NAME")
    return value


def sql_for(minutes):
    if not isinstance(minutes, int) or not 1 <= minutes <= 1440:
        raise ValueError("INVALID_LOOKBACK_MINUTES")
    # T543: all SELECTs inspect one consistent transaction and stable cutoff.
    # Independent live SELECTs raced Tape writes and caused spurious pair mismatches.
    matching = ("entity_type='POSTING' AND "
                "source_type='TRADE_ATOMIC_MATCH_PAIR_PREPARED' "
                "AND create_time>=@gate_window_start")
    return "\n".join([
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;",
        "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;",
        "SET @gate_now := NOW(3);",
        "SET @gate_window_start := DATE_SUB(@gate_now, INTERVAL %d MINUTE);" % minutes,
        "SELECT 'bootstrap_complete',COUNT(*) FROM dc_tenant_liquidity_bootstrap WHERE status='COMPLETE' AND step='DONE';",
        "SELECT 'robot_live',COUNT(*) FROM dc_tenant_robot WHERE enabled=1 AND runtime_status='RUNNING' "
        "AND open_order_count>=2 AND last_heartbeat_time>=DATE_SUB(@gate_now,INTERVAL 30 SECOND);",
        "SELECT 'robot_quote_orders',COALESCE(SUM(open_order_count),0) FROM dc_tenant_robot WHERE enabled=1 AND runtime_status='RUNNING';",
        "SELECT 'posting_rows',COUNT(*) FROM dc_trade_projection_mutation WHERE " + matching + ";",
        "SELECT 'posting_event_ids',COUNT(DISTINCT event_id) FROM dc_trade_projection_mutation WHERE " + matching + ";",
        "SELECT 'posting_locations',COUNT(DISTINCT location) FROM dc_trade_projection_mutation WHERE " + matching + ";",
        "SELECT 'bad_posting_pairs',COUNT(*) FROM (SELECT event_id FROM dc_trade_projection_mutation "
        "WHERE " + matching + " GROUP BY event_id HAVING COUNT(*)<>2) pair_check;",
        "SELECT 'balance_locations',COUNT(DISTINCT location) FROM dc_users_balance WHERE location<>'PLATFORM' "
        "AND update_time>=DATE_FORMAT(@gate_window_start,'%Y-%m-%d %H:%i:%s');",
        "SELECT 'projection_age_seconds',COALESCE(TIMESTAMPDIFF(SECOND,MAX(create_time),@gate_now),999999) "
        "FROM dc_trade_projection_event;",
        "COMMIT;",
        "",
    ])


def query_counts(mysql_container, lookback_minutes):
    args = ["docker", "exec", "-i", require_container(mysql_container), "sh", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N dc']
    result = subprocess.run(args, input=sql_for(lookback_minutes), text=True,
                            capture_output=True, check=False, timeout=90)
    if result.returncode:
        raise RuntimeError("READONLY_MYSQL_QUERY_FAILED")
    expected = {"bootstrap_complete", "robot_live", "robot_quote_orders", "posting_rows",
                "posting_event_ids", "posting_locations", "bad_posting_pairs",
                "balance_locations", "projection_age_seconds"}
    observed = {}
    for line in result.stdout.splitlines():
        values = line.split("\t")
        if len(values) == 2 and values[0] in expected:
            observed[values[0]] = int(values[1])
    if set(observed) != expected:
        raise RuntimeError("READONLY_MYSQL_CENSUS_INCOMPLETE")
    return observed


def tape_fills(lines):
    """Read only order publishes with a real filled IOC from the dedicated Tape trader."""
    events = []
    decoder = json.JSONDecoder()
    for line in lines:
        if ('RobotSvr-Tape' not in line or '"ExecType":"Trade"' not in line
                or '"OrdStatus":"Filled"' not in line):
            continue
        index = line.find("[{")
        if index < 0:
            continue
        try:
            report, _ = decoder.raw_decode(line[index:])
        except (ValueError, TypeError):
            continue
        if not isinstance(report, list):
            continue
        for event in report:
            if not isinstance(event, dict):
                continue
            if (event.get("Terminal") != "RobotSvr-Tape"
                    or event.get("TimeInForce") != "IOC"
                    or event.get("ExecType") != "Trade"
                    or event.get("OrdStatus") != "Filled"):
                continue
            exec_id = event.get("ExecID")
            location = event.get("Location")
            if not location and "dc.order.trade." in line:
                topic = line.split("dc.order.trade.", 1)[1].split(",[", 1)[0]
                location = topic.rsplit(".", 1)[-1]
            if exec_id and location and SAFE.fullmatch(location):
                events.append((location, exec_id))
    return events


def read_order_fills(container, since_utc):
    args = ["docker", "logs", "--since", since_utc, require_container(container)]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
    try:
        events = tape_fills(process.stdout)
        code = process.wait(timeout=20)
        if code:
            raise RuntimeError("ORDER_CONTAINER_LOG_READ_FAILED")
        return events
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def assess(counts, events, min_locations):
    problems = []
    if counts["bootstrap_complete"] < min_locations:
        problems.append("TRIAL_BOOTSTRAP_INCOMPLETE")
    if counts["robot_live"] < min_locations or counts["robot_quote_orders"] < 2 * min_locations:
        problems.append("ROBOT_QUOTES_NOT_LIVE")
    if counts["posting_rows"] < 2 * min_locations or counts["posting_locations"] < min_locations:
        problems.append("TRADE_POSTINGS_INCOMPLETE")
    if counts["posting_rows"] != 2 * counts["posting_event_ids"] or counts["bad_posting_pairs"] != 0:
        problems.append("TRADE_ATOMIC_POSTING_PAIR_MISMATCH")
    if counts["balance_locations"] < min_locations or counts["projection_age_seconds"] > 120:
        problems.append("TRADE_FINANCIAL_PROJECTION_NOT_CURRENT")
    if len(events) < min_locations or len(set(location for location, _ in events)) < min_locations:
        problems.append("TAPE_FILLED_IOC_NOT_PROVEN")
    ids = [eid for _, eid in events]
    if len(set(ids)) != len(ids):
        problems.append("TAPE_EXEC_ID_DUPLICATED")
    return sorted(problems)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", required=True)
    parser.add_argument("--order-a", required=True)
    parser.add_argument("--order-b", required=True)
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--min-locations", type=int, default=6)
    args = parser.parse_args()
    try:
        if not 1 <= args.min_locations <= 100:
            raise ValueError("INVALID_MIN_LOCATIONS")
        counts = query_counts(args.mysql, args.minutes)
        since = (datetime.now(timezone.utc) - timedelta(minutes=args.minutes)).isoformat(
            timespec="seconds").replace("+00:00", "Z")
        events = read_order_fills(args.order_a, since) + read_order_fills(args.order_b, since)
        reasons = assess(counts, events, args.min_locations)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "NO_GO", "reasons": ["E2E_EVIDENCE_UNAVAILABLE"]}))
        raise SystemExit(2)
    per_location = Counter(location for location, _ in events)
    print(json.dumps({
        "status": "NO_GO" if reasons else "PASS_LIVE_BUSINESS_NOT_HA",
        "min_locations": args.min_locations, "lookback_minutes": args.minutes,
        **counts,
        "tape_filled_ioc_reports": len(events),
        "tape_filled_unique_exec_ids": len(set(eid for _, eid in events)),
        "tape_filled_by_location": dict(sorted(per_location.items())),
        "reasons": reasons,
        "ha_sigkill_verified": False,
    }, sort_keys=True))
    if reasons:
        raise SystemExit(2)


if __name__ == "__main__":
    main()