#!/usr/bin/env python3
"""Verify projection-watermark SQL against small multi-epoch fixtures.

The SQL is extracted from the actual host checker, with MySQL's index hint
removed solely for SQLite execution. The production index access path is
verified separately against MySQL EXPLAIN on the live Demo.
"""
from pathlib import Path
import re
import sqlite3
import unittest


SCRIPT = Path(__file__).with_name("check-projection-consistency-host.sh")


def checker_query(variable):
    source = SCRIPT.read_text(encoding="utf-8")
    pattern = re.escape(variable) + r'="\$\(mysql_exec -e "\n(.*?)\n"\)"'
    match = re.search(pattern, source, flags=re.DOTALL)
    if match is None:
        raise AssertionError("missing embedded SQL for " + variable)
    return (match.group(1).replace("dc.", "")
            .replace("FORCE INDEX (uk_dc_order_projection_partition_seq)", ""))


class ProjectionWatermarkSQLTest(unittest.TestCase):
    def test_index_tail_matches_bruteforce_across_epochs(self):
        scenarios = [
            # Up-to-date watermark, with older epoch and older sequence.
            ([("A", 1, 1), ("A", 2, 1), ("A", 2, 3), ("B", 1, 1)],
             [("A", 2, 3), ("B", 1, 1)], 0),
            # Later event in same epoch not yet covered.
            ([("A", 2, 1), ("A", 2, 3)], [("A", 2, 1)], 1),
            # A newer source epoch exists.
            ([("A", 2, 3), ("A", 3, 1)], [("A", 2, 3)], 1),
            # A watermark ahead of all journal events.
            ([("A", 2, 3)], [("A", 2, 4)], 1),
            # The referenced partition has no event journal.
            ([], [("A", 2, 1)], 1),
            # Only one of multiple tenants is stale.
            ([("A", 1, 1), ("B", 1, 1), ("B", 1, 2)],
             [("A", 1, 1), ("B", 1, 1)], 1),
            # Old epoch and old event never invalidate the newest tail.
            ([("A", 1, 200), ("A", 2, 1)], [("A", 2, 1)], 0),
            # Nothing to compare: the host script separately disallows this.
            ([], [], 0),
        ]
        for kind in ("trade", "order"):
            with self.subTest(kind=kind):
                event_table = "dc_%s_projection_event" % kind
                wm_table = "dc_%s_projection_watermark" % kind
                db = sqlite3.connect(":memory:")
                db.execute("CREATE TABLE %s (partition_id TEXT, source_epoch INT, "
                           "journal_seq INT, UNIQUE(partition_id,source_epoch,journal_seq))"
                           % event_table)
                db.execute("CREATE TABLE %s (partition_id TEXT PRIMARY KEY, "
                           "source_epoch INT, journal_seq INT)" % wm_table)
                query = checker_query(("%s_watermark_mismatch" % kind)
                                      if kind == "order" else "watermark_mismatch")
                for events, watermarks, expected in scenarios:
                    db.execute("DELETE FROM %s" % event_table)
                    db.execute("DELETE FROM %s" % wm_table)
                    db.executemany("INSERT INTO %s VALUES (?,?,?)" % event_table, events)
                    db.executemany("INSERT INTO %s VALUES (?,?,?)" % wm_table, watermarks)
                    actual = db.execute(query).fetchone()[0]
                    self.assertEqual(actual, expected, (kind, events, watermarks))
                db.close()


if __name__ == "__main__":
    unittest.main()
