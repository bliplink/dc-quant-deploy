#!/usr/bin/env python3
"""Bounded, read-only orphan audit for the Trade Projection event journal.

Checks mutations by index-order chunks. It never writes SQL or treats a live,
non-transactional key-range scan as a durable consistent snapshot.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

IDENT = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
PK = ("partition_id", "source_epoch", "journal_seq", "mutation_index")


def parse_key(parts):
    if len(parts) != 4 or not IDENT.fullmatch(parts[0]):
        raise ValueError("invalid mutation primary key")
    ints = []
    for part in parts[1:]:
        if not re.fullmatch(r"[0-9]{1,19}", part):
            raise ValueError("invalid mutation primary key integer")
        ints.append(int(part))
    return (parts[0],) + tuple(ints)


def sql_key(key):
    if len(key) != 4 or not IDENT.fullmatch(key[0]) or any(
            not isinstance(v, int) or v < 0 or v > 2**63 - 1 for v in key[1:]):
        raise ValueError("unsafe key")
    return "('%s',%d,%d,%d)" % key


def query_bound():
    order = ",".join("%s DESC" % column for column in PK)
    return ("SELECT " + ",".join(PK) +
            " FROM dc.dc_trade_projection_mutation FORCE INDEX (PRIMARY)"
            " ORDER BY " + order + " LIMIT 1;")


def query_page(cursor, ceiling, limit, max_ms):
    if limit < 1 or limit > 50000 or max_ms < 1000 or max_ms > 30000:
        raise ValueError("query limits out of bounds")
    key = "(" + ",".join("m." + column for column in PK) + ")"
    predicate = " AND ".join((
        key + " > " + sql_key(cursor) if cursor else "1=1",
        key + " <= " + sql_key(ceiling)))
    fields = ",".join("m." + column for column in PK)
    order = ",".join("m." + column for column in PK)
    return (
        "SELECT /*+ MAX_EXECUTION_TIME(%d) */ " % max_ms +
        ",".join("b." + column for column in PK) +
        ",IF(e.partition_id IS NULL,1,0) "
        "FROM (SELECT " + fields +
        " FROM dc.dc_trade_projection_mutation m FORCE INDEX(PRIMARY)"
        " WHERE " + predicate +
        " ORDER BY " + order + " LIMIT %d) b " % limit +
        "LEFT JOIN dc.dc_trade_projection_event e FORCE INDEX(PRIMARY)"
        " ON e.partition_id=b.partition_id AND e.source_epoch=b.source_epoch"
        " AND e.journal_seq=b.journal_seq"
        " ORDER BY " + ",".join("b." + column for column in PK) + ";"
    )


def mysql_query(sql, container, username, seconds):
    env = os.environ.copy()
    password = env.get("MYSQL_PASSWORD")
    if not password:
        raise ValueError("MYSQL_PASSWORD environment missing")
    env["MYSQL_PWD"] = password
    cmd = ["docker", "exec", "-e", "MYSQL_PWD", container, "mysql",
           "-u" + username, "--batch", "--raw", "--skip-column-names", "-e", sql]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True,
                         timeout=seconds, check=False)
    if res.returncode != 0:
        raise RuntimeError("bounded MySQL audit query failed: " +
                           res.stderr[:200].replace(password, "<redacted>"))
    return [line.split("\t") for line in res.stdout.splitlines() if line]


def scan(query, chunk_size=10000, max_seconds=90, max_pages=1000,
         query_timeout=10):
    if not 1 <= chunk_size <= 50000 or not 1 <= max_pages <= 10000:
        raise ValueError("invalid page settings")
    if not 5 <= max_seconds <= 1800 or not 2 <= query_timeout <= 35:
        raise ValueError("invalid time settings")
    started = time.monotonic()
    upper = query(query_bound())
    if len(upper) != 1:
        raise ValueError("missing/ambiguous mutation upper bound")
    ceiling = parse_key(upper[0])
    report = {
        "schema": "otc-trade-projection-orphan-range-v1",
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_BOUNDED_LIVE_OBSERVATION",
        "fixedUpperKey": list(ceiling),
        "consistentTransaction": False, "liveConcurrentBackfillExcluded": False,
        "authoritativeAttestation": False, "scanned": 0, "orphanMutations": 0,
        "pages": 0, "decision": "PARTIAL_NOT_ATTESTED",
    }
    cursor = None
    while report["pages"] < max_pages and time.monotonic() - started < max_seconds:
        sql = query_page(cursor, ceiling, chunk_size, min(query_timeout * 1000, 30000))
        rows = query(sql)
        if len(rows) > chunk_size:
            raise RuntimeError("bounded query returned too many rows")
        for row in rows:
            if len(row) != 5 or row[4] not in ("0", "1"):
                raise ValueError("unparseable orphan audit row")
            parsed = parse_key(row[:4])
            if cursor is not None and parsed <= cursor:
                raise ValueError("cursor did not advance in strict key order")
            cursor = parsed
            report["scanned"] += 1
            report["orphanMutations"] += int(row[4])
        report["pages"] += 1
        if report["orphanMutations"]:
            report["decision"] = "FAIL_ORPHANS_FOUND"
            break
        if rows and cursor == ceiling:
            # All rows <= fixed upper bound were visited once; this is NOT an
            # MVCC snapshot and cannot prove safety against concurrent inserts.
            report["decision"] = "PASS_LIVE_RANGE_OBSERVATION_ONLY"
            break
        if len(rows) < chunk_size:
            # An initially observed ceiling cannot disappear from a consistent
            # range: a mutation was deleted during the scan, or paging broke.
            raise RuntimeError("fixed upper key not reached; possible concurrent deletion")
    report["lastScannedKey"] = list(cursor) if cursor else None
    report["elapsedSeconds"] = round(time.monotonic() - started, 3)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="dc-saas-mysql")
    parser.add_argument("--chunk-size", type=int, default=10000)
    parser.add_argument("--max-seconds", type=int, default=90)
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--query-timeout", type=int, default=10)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    if not IDENT.fullmatch(args.container):
        parser.error("unsafe container")
    username = os.environ.get("MYSQL_USERNAME", "")
    if not IDENT.fullmatch(username):
        parser.error("MYSQL_USERNAME environment missing or unsafe")
    if args.report.exists() or args.report.is_symlink():
        parser.error("report must not already exist")
    def query(sql):
        return mysql_query(sql, args.container, username, args.query_timeout + 3)
    try:
        result = scan(query, args.chunk_size, args.max_seconds, args.max_pages,
                      args.query_timeout)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = {"schema": "otc-trade-projection-orphan-range-v1",
                  "mode": "READ_ONLY_BOUNDED_LIVE_OBSERVATION",
                  "decision": "INCOMPLETE_ERROR_NOT_ATTESTED",
                  "authoritativeAttestation": False,
                  "error": str(exc)[:240]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf8") as dest:
        json.dump(result, dest, indent=2, ensure_ascii=False)
        dest.write("\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["decision"] == "PASS_LIVE_RANGE_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    sys.exit(main())
