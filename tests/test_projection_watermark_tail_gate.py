"""Regression tests for the read-only Production Projection DB watermark gate."""
import importlib.util
from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
