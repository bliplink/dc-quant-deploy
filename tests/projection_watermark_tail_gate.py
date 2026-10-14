#!/usr/bin/env python3
"""Read-only preflight for Projection database watermark vs persisted event tails.

Checks Order and Trade partitions which have durable watermark rows.
The checks are necessary but NOT sufficient for rollout: they do not compare
the database to authoritative Order/Trade committed journals or snapshots.
NEVER adjusts any watermark, deletes data or restarts Docker containers.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys

STREAMS = ("order", "trade")


def issues_for_snapshot(snapshot):
    problems = []
    for stream in STREAMS:
        rows = snapshot.get(stream)
        if not isinstance(rows, list) or not rows:
            problems.append("%s watermark/event evidence missing" % stream)
            continue
        seen = set()
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != 5:
                problems.append("%s incomplete watermark/tail row" % stream)
                continue
            partition, epoch, seq, tail_epoch, tail_seq = row
            if not isinstance(partition, str) or not partition.startswith("P"):
                problems.append("%s invalid partition" % stream)
                continue
            if partition in seen:
                problems.append("%s duplicate partition %s" % (stream, partition))
            seen.add(partition)
            try:
                ep = int(epoch)
                sq = int(seq)
                te = int(tail_epoch)
                ts = int(tail_seq)
            except (TypeError, ValueError):
                problems.append("%s %s missing or invalid event tail" % (stream, partition))
                continue
            if ep != te or sq != ts:
                problems.append("%s %s DB watermark %s/%s != DB event tail %s/%s" %
                                (stream, partition, ep, sq, te, ts))
    return problems


def read_db_rows(sql, stream):
    """Bound the audit's impact even when the database is under write load."""
    result = subprocess.run(
        ["docker", "exec", "dc-saas-mysql", "sh", "-lc",
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N dc -e ' + shlex.quote(sql)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    if result.returncode:
        # Never print database credentials or the SQL client's error context.
        raise RuntimeError("%s read failed, exit=%s" % (stream, result.returncode))
    return [line.split("\t") for line in result.stdout.splitlines() if line.strip()]


def tail_sql(stream, partitions):
    """Constant-key index probes avoid MySQL's correlated-subquery filesort."""
    if stream not in STREAMS or len(partitions) > 256:
        raise ValueError("invalid Projection stream or partition count")
    table = "dc_%s_projection_event" % stream
    index = ("uk_dc_order_projection_partition_seq" if stream == "order"
             else "PRIMARY")
    statements = ["SET SESSION MAX_EXECUTION_TIME=1500"]
    for partition in partitions:
        if not re.fullmatch(r"P[0-9]{3}", partition):
            raise ValueError("invalid Projection partition identifier")
        statements.append(
            "SELECT '{0}',e.source_epoch,e.journal_seq FROM {1} e "
            "FORCE INDEX({2}) WHERE e.partition_id='{0}' "
            "ORDER BY e.source_epoch DESC,e.journal_seq DESC LIMIT 1"
            .format(partition, table, index))
    return ";\n".join(statements) + ";\n"


def consistent_read_sql():
    """Fetch both streams in ONE read-only REPEATABLE READ snapshot.

    Two independent MySQL sessions can falsely report a watermark/tail drift
    while Robot writes continue. Index seeks are bounded to 257 watermarks
    per stream; no table scan, mutation, ZK action or external side effect.
    """
    statements = [
        "SET SESSION MAX_EXECUTION_TIME=1500",
        "SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY",
    ]
    for stream in STREAMS:
        prefix = "dc_%s_projection" % stream
        event = prefix + "_event"
        idx = ("uk_dc_order_projection_partition_seq" if stream == "order"
               else "PRIMARY")
        tail_epoch = ("(SELECT e.source_epoch FROM %s e FORCE INDEX (%s) "
                      "WHERE e.partition_id=w.partition_id ORDER BY "
                      "e.source_epoch DESC,e.journal_seq DESC LIMIT 1)" % (event, idx))
        tail_seq = ("(SELECT e.journal_seq FROM %s e FORCE INDEX (%s) "
                    "WHERE e.partition_id=w.partition_id ORDER BY "
                    "e.source_epoch DESC,e.journal_seq DESC LIMIT 1)" % (event, idx))
        statements.append(
            "SELECT '%s',w.partition_id,w.source_epoch,w.journal_seq,%s,%s "
            "FROM %s_watermark w ORDER BY w.partition_id LIMIT 257" %
            (stream, tail_epoch, tail_seq, prefix))
    statements.append("COMMIT")
    return ";\n".join(statements) + ";\n"


def read_consistent_db_snapshot_rows(sql):
    command = ["docker", "exec", "-i", "dc-saas-mysql", "sh", "-lc",
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N dc']
    result = subprocess.run(command, input=sql, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=30)
    if result.returncode:
        # Never expose Docker MySQL passwords or SQL client stderr.
        raise RuntimeError("read-only consistent Projection snapshot failed")
    return [line.split("\t") for line in result.stdout.splitlines() if line.strip()]


def db_snapshot():
    snapshot = {stream: [] for stream in STREAMS}
    rows = read_consistent_db_snapshot_rows(consistent_read_sql())
    for row in rows:
        if len(row) != 6 or row[0] not in STREAMS:
            raise ValueError("unexpected read-only Projection snapshot row")
        stream, *values = row
        snapshot[stream].append(values)
    for stream, records in snapshot.items():
        if len(records) > 256 or any(len(row) != 5 for row in records):
            raise ValueError("%s invalid watermark catalog" % stream)
        partitions = [row[0] for row in records]
        if len(partitions) != len(set(partitions)) or any(
                not re.fullmatch(r"P[0-9]{3}", part) for part in partitions):
            raise ValueError("%s unsafe/duplicate watermark partition" % stream)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", help="offline JSON for tests; otherwise read live MySQL")
    args = parser.parse_args()
    try:
        if args.snapshot:
            with open(args.snapshot, encoding="utf-8") as fh:
                evidence = json.load(fh)
        else:
            evidence = db_snapshot()
        problems = issues_for_snapshot(evidence)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        print("PROJECTION_WATERMARK_TAIL_NO_GO: cannot verify evidence: %s" % str(e))
        return 2
    print("Projection DB evidence order_rows=%d trade_rows=%d" %
          (len(evidence.get("order", [])), len(evidence.get("trade", []))))
    if problems:
        print("PROJECTION_WATERMARK_TAIL_NO_GO")
        for issue in problems[:60]:
            print(" - " + issue)
        return 2
    print("PROJECTION_DB_TAIL_MATCH (not HA rollout authorization; "
          "must compare committed source journals and replica epochs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
