"""Observe the existing Demo Robot without starting or pausing its workload."""
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
import time

from check_trial_robot_trade_e2_readonly import tape_fills


ROBOT = "dc-saas-robotsvr"
SAFE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
LOCAL = re.compile(r"TRADE_LOCAL_MATCH_RECEIPT location=([A-Za-z0-9_-]+) symbol=\S+ "
                   r"coordinate=(P\d{3})/(\d+)/(\d+) quorumDurable=false rpoRisk=true")
DECODER = json.JSONDecoder()


def utc_now():
    return datetime.now(timezone.utc)


def logs(container, since, until):
    command = ["docker", "logs", "--timestamps", "--since", since.isoformat(), "--until", until.isoformat(), container]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=True, timeout=30)
    return (result.stdout + "\n" + result.stderr).splitlines()


def snapshot(order, trade, since, until):
    quotes, requests, local = set(), set(), set()
    for container in trade:
        for line in logs(container, since, until):
            match = LOCAL.search(line)
            if match:
                location, partition, epoch, sequence = match.groups()
                local.add((location, partition, int(epoch), int(sequence)))
            if '"ExecType":"Newing"' not in line or "INFO sid:" not in line or "UpdateOrderHandler:" not in line:
                continue
            try:
                report, _ = DECODER.raw_decode(line[line.index("{", line.index("INFO sid:")):])
            except ValueError:
                continue
            location, request = report.get("Location", ""), report.get("ClOrdID", "")
            if not SAFE.fullmatch(location) or not SAFE.fullmatch(request):
                continue
            if report.get("Terminal") == "RobotSvr" and report.get("Side") in {"Buy", "Sell"}:
                quotes.add((location, report["Side"], request))
            elif report.get("Terminal") == "RobotSvr-Tape" and report.get("TimeInForce") == "IOC":
                requests.add((location, request))
    fills = [event for container in order for event in tape_fills(logs(container, since, until))]
    return quotes, requests, local, fills


def rounds(location, since, until):
    pattern = re.compile(r"^(\S+) .*ROBOT_T420_PHASE phase=BEGIN location=" + re.escape(location) + r"(?:\s|$)")
    ticks = set()
    for line in logs(ROBOT, since, until):
        match = pattern.search(line)
        if match:
            stamp = re.sub(r"(\.\d{6})\d*Z$", r"\1+00:00", match[1]).replace("Z", "+00:00")
            ticks.add(datetime.fromisoformat(stamp))
    points = [since, *sorted(ticks), until]
    gap = max((b - a).total_seconds() for a, b in zip(points, points[1:]))
    if len(ticks) < 2 or gap > 100:
        raise RuntimeError(f"Robot {location} did not sustain its loop across the fault (rounds={len(ticks)}, max_gap={gap:.1f}s)")
    return {"rounds": len(ticks), "max_gap_seconds": round(gap, 3)}


def wait_traffic(order, trade, since, location=None, local_routes=None, previous_quotes=(), seconds=160,
                 prefer_location=None):
    deadline = time.monotonic() + seconds
    known = {request for _, request in previous_quotes}
    while time.monotonic() < deadline:
        now = utc_now()
        begin = since if location else now - timedelta(seconds=180)
        quotes, requests, local, fills = snapshot(order, trade, begin, now)
        candidates = [location] if location else sorted(
            {tenant for tenant, _ in fills},
            key=lambda tenant: (prefer_location is not None and not prefer_location(tenant), tenant))
        for tenant in candidates:
            fresh_quotes = sorted((side, request) for t, side, request in quotes if t == tenant and request not in known)
            fresh_requests = sorted(r for t, r in requests if t == tenant)
            tape = [exec_id for t, exec_id in fills if t == tenant]
            if len(tape) != len(set(tape)):
                raise RuntimeError(f"Duplicate Tape execution for Robot {tenant}")
            commits = sorted((part, epoch, seq) for t, part, epoch, seq in local
                             if t == tenant and local_routes and local_routes.get(part, {}).get("epoch") == epoch)
            if fresh_quotes and tape and (commits and fresh_requests if local_routes else True):
                return {"location": tenant, "since": begin.isoformat(), "until": now.isoformat(),
                        "quote_requests": fresh_quotes, "tape_requests": fresh_requests,
                        "tape_execution_ids": tape, "local_trade_commits": commits}
        time.sleep(4)
    message = "Robot did not produce fresh quote requests and certified execution evidence in this phase"
    if location and SAFE.fullmatch(location):
        sql = ("SELECT runtime_status,COALESCE(last_error_code,''),open_order_count,"
               "CASE WHEN last_error_message LIKE '%ORDER_COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED%' "
               "THEN 'ORDER_COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED' ELSE '' END "
               f"FROM dc_tenant_robot WHERE location='{location}' AND security_id='BTCUSDT' ORDER BY robot_id")
        try:
            result = subprocess.run(["docker", "exec", "dc-saas-mysql", "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N dc -e "$1"', "--", sql],
                capture_output=True, text=True, timeout=8, check=True)
            message += f" for {location} (status, code, open orders, Common denial: {result.stdout.strip()!r})"
        except (OSError, subprocess.SubprocessError):
            pass
    raise RuntimeError(message)


def require_posting_pairs(traffic):
    location = traffic["location"]
    execution_ids = traffic["tape_execution_ids"]
    commits = {tuple(row) for row in traffic["local_trade_commits"]}
    if not SAFE.fullmatch(location) or not all(SAFE.fullmatch(exec_id) for exec_id in execution_ids):
        raise RuntimeError("Unexpected Robot settlement identity")
    requested = ",".join("'" + value + "'" for value in execution_ids) or "''"
    sql = ("SELECT partition_id,source_epoch,journal_seq,event_id,COUNT(*),"
           "GROUP_CONCAT(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.sourceID'))) "
           "FROM dc_trade_projection_mutation "
           f"WHERE location='{location}' AND entity_type='POSTING' AND source_type='TRADE_ATOMIC_MATCH_PAIR_PREPARED' "
           "GROUP BY partition_id,source_epoch,journal_seq,event_id HAVING "
           f"SUM(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.sourceID')) IN ({requested}))>0 "
           "OR (partition_id,source_epoch,journal_seq) IN (" + (
               ",".join(f"('{part}',{epoch},{seq})" for part, epoch, seq in sorted(commits)) or "('',0,0)") + ")")
    command = ["docker", "exec", "dc-saas-mysql", "sh", "-c",
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N dc -e "$1"', "--", sql]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=25)
        coordinates, ids, events = set(), [], []
        for line in result.stdout.splitlines():
            part, epoch, seq, event, count, sources = line.split("\t")
            if int(count) != 2:
                raise RuntimeError("Robot settlement has an invalid number of postings")
            coordinates.add((part, int(epoch), int(seq)))
            ids.extend(value for value in sources.split(",") if value in execution_ids)
            events.append(event)
        if commits <= coordinates and sorted(execution_ids) == sorted(ids):
            return sorted(events)
        time.sleep(3)
    raise RuntimeError("Robot executions did not converge to two postings at their original Trade coordinates")
