import importlib.util
from pathlib import Path
import sqlite3
import re
import unittest


FILE = Path(__file__).resolve().parents[1] / "scripts/check-projection-orphans-batched.py"
spec = importlib.util.spec_from_file_location("orphan_scan", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class OrphanBatchTest(unittest.TestCase):
    def database(self):
        db = sqlite3.connect(":memory:")
        db.execute("ATTACH DATABASE ':memory:' AS dc")
        db.execute("CREATE TABLE dc.dc_trade_projection_mutation (partition_id TEXT, "
                   "source_epoch INT, journal_seq INT, mutation_index INT, "
                   "PRIMARY KEY(partition_id, source_epoch, journal_seq, mutation_index))")
        db.execute("CREATE TABLE dc.dc_trade_projection_event (partition_id TEXT, "
                   "source_epoch INT, journal_seq INT, "
                   "PRIMARY KEY(partition_id, source_epoch, journal_seq))")
        mutations = [("A", 1, 1, 0), ("A", 1, 1, 1), ("A", 1, 2, 0),
                     ("B", 2, 1, 0), ("B", 2, 1, 1)]
        db.executemany("INSERT INTO dc.dc_trade_projection_mutation VALUES (?,?,?,?)",
                       mutations)
        db.executemany("INSERT INTO dc.dc_trade_projection_event VALUES (?,?,?)",
                       [("A", 1, 1), ("A", 1, 2), ("B", 2, 1)])
        return db

    @staticmethod
    def runner(db):
        def query(sql):
            sql = sql.replace(" FORCE INDEX (PRIMARY)", "")
            sql = sql.replace(" FORCE INDEX(PRIMARY)", "")
            sql = sql.replace("IF(e.partition_id IS NULL,1,0)",
                              "CASE WHEN e.partition_id IS NULL THEN 1 ELSE 0 END")
            return [list(map(str, row)) for row in db.execute(sql).fetchall()]
        return query

    def test_complete_small_batches(self):
        db = self.database()
        try:
            result = mod.scan(self.runner(db), chunk_size=2, max_pages=20)
            self.assertEqual(result["decision"], "PASS_LIVE_RANGE_OBSERVATION_ONLY")
            self.assertEqual(result["scanned"], 5)
            self.assertEqual(result["orphanMutations"], 0)
            self.assertEqual(result["pages"], 3)
            self.assertFalse(result["authoritativeAttestation"])
        finally:
            db.close()

    def test_orphan_detected_and_fails_closed(self):
        db = self.database()
        try:
            db.execute("DELETE FROM dc.dc_trade_projection_event WHERE partition_id='B'")
            result = mod.scan(self.runner(db), chunk_size=2, max_pages=20)
            self.assertEqual(result["decision"], "FAIL_ORPHANS_FOUND")
            self.assertGreater(result["orphanMutations"], 0)
        finally:
            db.close()

    def test_page_cap_returns_incomplete(self):
        db = self.database()
        try:
            result = mod.scan(self.runner(db), chunk_size=2, max_pages=1)
            self.assertEqual(result["decision"], "PARTIAL_NOT_ATTESTED")
            self.assertEqual(result["scanned"], 2)
            self.assertFalse(result["authoritativeAttestation"])
        finally:
            db.close()

    def test_latest_epoch_and_lexical_partition_order(self):
        db = self.database()
        try:
            db.execute("INSERT INTO dc.dc_trade_projection_mutation VALUES ('B',3,1,0)")
            db.execute("INSERT INTO dc.dc_trade_projection_event VALUES ('B',3,1)")
            result = mod.scan(self.runner(db), chunk_size=3, max_pages=20)
            self.assertEqual(result["decision"], "PASS_LIVE_RANGE_OBSERVATION_ONLY")
            self.assertEqual(result["fixedUpperKey"], ["B", 3, 1, 0])
            self.assertEqual(result["scanned"], 6)
        finally:
            db.close()

    def test_missing_fixed_upper_key_fails_closed(self):
        db = self.database()
        try:
            inner = self.runner(db)
            counter = [0]
            def missing_during_scan(sql):
                counter[0] += 1
                if counter[0] == 2:
                    db.execute("DELETE FROM dc.dc_trade_projection_mutation "
                               "WHERE partition_id='B' AND mutation_index=1")
                return inner(sql)
            with self.assertRaisesRegex(RuntimeError, "fixed upper key not reached"):
                mod.scan(missing_during_scan, chunk_size=2, max_pages=20)
        finally:
            db.close()

    def test_cross_partition_conflict_sql_finds_duplicate_or_none(self):
        text = (FILE.parents[1] / 'tests/check-projection-consistency-host.sh').read_text()
        line = next(line for line in text.splitlines()
                    if line.startswith('cross_partition_event_ids="$(mysql_exec -e "'))
        sql = line.split('mysql_exec -e "', 1)[1].rsplit('")"', 1)[0]
        sql = sql.replace('dc.', '').replace(
            ' FORCE INDEX(idx_trade_projection_event_id)', '')
        self.assertNotIn('GROUP BY', sql)
        db = self.database()
        try:
            db.execute('ALTER TABLE dc.dc_trade_projection_event ADD COLUMN event_id TEXT')
            db.execute("UPDATE dc.dc_trade_projection_event SET event_id='shared' "
                       "WHERE partition_id='A' AND journal_seq=1")
            db.execute("UPDATE dc.dc_trade_projection_event SET event_id='unique' "
                       "WHERE partition_id='A' AND journal_seq=2")
            db.execute("UPDATE dc.dc_trade_projection_event SET event_id='different' "
                       "WHERE partition_id='B'")
            self.assertEqual(db.execute(sql).fetchone()[0], 0)
            db.execute("UPDATE dc.dc_trade_projection_event SET event_id='shared' "
                       "WHERE partition_id='B'")
            self.assertEqual(db.execute(sql).fetchone()[0], 1)
        finally:
            db.close()

    def test_invalid_key_rejected(self):
        for unsafe in [("x' OR 1=1 --", 1, 2, 3), ("A", -1, 2, 3)]:
            with self.assertRaises(ValueError):
                mod.sql_key(unsafe)
        with self.assertRaises(ValueError):
            mod.parse_key(["A", "1", "2", "nan"])


if __name__ == "__main__":
    unittest.main()
