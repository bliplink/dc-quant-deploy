"""Regression tests for the read-only Production Projection DB watermark gate."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "projection_watermark_tail_gate.py"
spec = importlib.util.spec_from_file_location("projection_watermark_tail_gate", str(SCRIPT))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ProjectionWatermarkTailGateTest(unittest.TestCase):
    def test_all_matching_is_db_precheck_only(self):
        snapshot = {
            "order": [["P054", "85", "109062", "85", "109062"]],
            "trade": [["P232", "1", "7025", "1", "7025"]],
        }
        self.assertEqual([], gate.issues_for_snapshot(snapshot))

    def test_known_live_inconsistent_partitions_are_no_go(self):
        snapshot = {
            "order": [["P054", "85", "109061", "85", "109062"],
                      ["P138", "85", "9146", "85", "9151"]],
            "trade": [["P123", "1", "3915", "1", "3917"],
                      ["P186", "1", "9485", "1", "9487"]],
        }
        issues = gate.issues_for_snapshot(snapshot)
        self.assertEqual(4, len(issues))
        for partition in ("P054", "P138", "P123", "P186"):
            self.assertTrue(any(partition in issue for issue in issues))

    def test_never_ignore_watermark_ahead_of_tail(self):
        snapshot = {"order": [["P054", "85", "1100", "85", "1099"]],
                    "trade": [["P232", "1", "7025", "1", "7025"]]}
        self.assertEqual(1, len(gate.issues_for_snapshot(snapshot)))

    def test_epoch_mismatch_blocks_even_if_sequence_matches(self):
        snapshot = {"order": [["P054", "86", "1", "85", "1"]],
                    "trade": [["P232", "1", "7025", "1", "7025"]]}
        self.assertEqual(1, len(gate.issues_for_snapshot(snapshot)))

    def test_missing_or_duplicate_rows_fail_closed(self):
        self.assertGreater(len(gate.issues_for_snapshot({"order": [], "trade": []})), 0)
        snapshot = {"order": [["P054", "85", "109062", "85", "109062"],
                              ["P054", "85", "109062", "85", "109062"]],
                    "trade": [["P232", "1", "7025", "NULL", "NULL"]]}
        self.assertEqual(2, len(gate.issues_for_snapshot(snapshot)))

    def test_unexpected_input_types_fail_closed(self):
        snapshot = {"order": [None, ["P001", "not-number", "1", "1", "1"]],
                    "trade": "not-rows"}
        self.assertEqual(3, len(gate.issues_for_snapshot(snapshot)))

    def test_tail_sql_uses_constant_partition_index_seeks(self):
        order = gate.tail_sql("order", ["P023", "P054"])
        trade = gate.tail_sql("trade", ["P023"])
        self.assertIn("FORCE INDEX(uk_dc_order_projection_partition_seq)", order)
        self.assertIn("FORCE INDEX(PRIMARY)", trade)
        self.assertIn("MAX_EXECUTION_TIME=1500", order)
        self.assertIn("e.partition_id='P023'", trade)
        self.assertNotIn("w.partition_id", order)
        with self.assertRaises(ValueError):
            gate.tail_sql("trade", ["P023'; DROP TABLE x"])
        with self.assertRaises(ValueError):
            gate.tail_sql("trade", ["P%03d" % x for x in range(257)])

    def _catalog(self):
        return {"order": ["P001"], "trade": ["P002"]}

    def test_db_snapshot_preserves_missing_tail_as_block(self):
        rows = [["W", "order", "P001", "2", "50"],
                ["W", "trade", "P002", "1", "20"],
                ["T", "trade", "P002", "1", "20"]]
        with mock.patch.object(gate, "catalog_snapshot", return_value=self._catalog()):
            with mock.patch.object(gate, "read_consistent_db_snapshot_rows", return_value=rows):
                evidence = gate.db_snapshot()
        self.assertEqual(["P001", "2", "50", "NULL", "NULL"],
                         evidence["order"][0])
        self.assertEqual(1, len(gate.issues_for_snapshot(evidence)))

    def test_db_snapshot_refuses_duplicate_event_tail(self):
        rows = [["W", "order", "P001", "2", "50"],
                ["W", "trade", "P002", "1", "20"],
                ["T", "order", "P001", "2", "50"],
                ["T", "order", "P001", "2", "50"]]
        with mock.patch.object(gate, "catalog_snapshot", return_value=self._catalog()):
            with mock.patch.object(gate, "read_consistent_db_snapshot_rows", return_value=rows):
                with self.assertRaisesRegex(ValueError, "duplicate T partition"):
                    gate.db_snapshot()

    def test_db_snapshot_uses_one_readonly_consistent_mysql_session(self):
        sql = gate.consistent_read_sql(self._catalog())
        self.assertIn("WITH CONSISTENT SNAPSHOT, READ ONLY", sql)
        self.assertEqual(1, sql.count("START TRANSACTION"))
        self.assertIn("FORCE INDEX (uk_dc_order_projection_partition_seq)", sql)
        self.assertIn("FORCE INDEX (PRIMARY)", sql)
        self.assertIn("MAX_EXECUTION_TIME=1500", sql)
        self.assertIn("e.partition_id='P001'", sql)
        self.assertIn("e.partition_id='P002'", sql)
        self.assertNotIn("WHERE e.partition_id=w.partition_id", sql)
        self.assertEqual(1, sql.count("COMMIT"))
        rows = [["W", "order", "P001", "1", "50"],
                ["W", "trade", "P002", "1", "20"],
                ["T", "order", "P001", "1", "50"],
                ["T", "trade", "P002", "1", "20"]]
        with mock.patch.object(gate, "catalog_snapshot", return_value=self._catalog()):
            with mock.patch.object(gate, "read_consistent_db_snapshot_rows", return_value=rows) as read:
                self.assertEqual([], gate.issues_for_snapshot(gate.db_snapshot()))
                self.assertEqual(1, read.call_count)

    def test_db_snapshot_rejects_extra_or_unknown_rows(self):
        rows = [["W", "order", "P001", "1", "1"],
                ["unknown", "trade", "P002", "1", "1"]]
        with mock.patch.object(gate, "catalog_snapshot", return_value=self._catalog()):
            with mock.patch.object(gate, "read_consistent_db_snapshot_rows", return_value=rows):
                with self.assertRaisesRegex(ValueError, "unexpected"):
                    gate.db_snapshot()

    def test_db_snapshot_rejects_new_watermark_partition_not_in_preflight(self):
        rows = [["W", "order", "P001", "1", "1"],
                ["W", "order", "P054", "1", "2"],
                ["W", "trade", "P002", "1", "1"]]
        with mock.patch.object(gate, "catalog_snapshot", return_value=self._catalog()):
            with mock.patch.object(gate, "read_consistent_db_snapshot_rows", return_value=rows):
                with self.assertRaisesRegex(ValueError, "changed watermark catalog"):
                    gate.db_snapshot()

    def test_cannot_inject_sql_through_preliminary_catalog(self):
        for bad in (["P001';DROP TABLE x"], ["P001", "P001"], ["P9999"]):
            catalog = {"order": bad, "trade": ["P002"]}
            with self.assertRaises(ValueError):
                gate.consistent_read_sql(catalog)


if __name__ == "__main__":
    unittest.main()
