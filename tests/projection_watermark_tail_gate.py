#!/usr/bin/env python3
"""Read-only preflight for Projection database watermark vs persisted event tails.

Checks Order and Trade partitions which have durable watermark rows.
The checks are necessary but NOT sufficient for rollout: they do not compare
the database to authoritative Order/Trade committed journals or snapshots.
NEVER adjusts any watermark, deletes data or restarts Docker containers.
"""
import argparse
import json
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


def db_snapshot():
    snapshot = {}
    for stream in STREAMS:
        table_prefix = "dc_%s_projection" % stream
        # A correlated top-1 seeks the (partition,epoch,seq) index for each
        # existing watermark row. Avoid a full multi-million-event GROUP BY.
        sql = ("SELECT w.partition_id,w.source_epoch,w.journal_seq,"
               "(SELECT e.source_epoch FROM {0}_event e WHERE e.partition_id=w.partition_id "
               "ORDER BY e.source_epoch DESC,e.journal_seq DESC LIMIT 1),"
               "(SELECT e.journal_seq FROM {0}_event e WHERE e.partition_id=w.partition_id "
               "ORDER BY e.source_epoch DESC,e.journal_seq DESC LIMIT 1) "
               "FROM {0}_watermark w ORDER BY w.partition_id;").format(table_prefix)
        result = subprocess.run(
            ["docker", "exec", "dc-saas-mysql", "sh", "-lc",
             'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N dc -e ' + shlex.quote(sql)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=65)
        if result.returncode:
            raise RuntimeError("%s read failed, exit=%s: %s" %
                               (stream, result.returncode, result.stderr[:150]))
        snapshot[stream] = [line.split("\t") for line in result.stdout.splitlines() if line.strip()]
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
