import json
import tempfile
import unittest
from pathlib import Path

from run_local_strategy_batch_chunks import aggregate_results, result_path


class ChunkedBatchTest(unittest.TestCase):
    def test_extracts_last_summary_path(self):
        output = "x\nBATCH_SUMMARY=C:\\first.json\ny\nBATCH_SUMMARY=C:\\last.json\n"
        self.assertEqual(r"C:\last.json", str(result_path(output)))

    def test_returns_none_without_marker(self):
        self.assertIsNone(result_path("no summary"))

    def test_aggregate_ignores_errors_and_keeps_latest_valid_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(json.dumps({"results": [
                {"strategyName": "one", "symbol": "BTC", "qualified": False},
                {"strategyName": "bad", "executionError": True},
            ]}), encoding="utf-8")
            second.write_text(json.dumps({"results": [
                {"strategyName": "one", "symbol": "BTC", "qualified": True},
            ]}), encoding="utf-8")
            rows = aggregate_results([
                {"summaryPath": str(first)}, {"summaryPath": str(second)}])
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["qualified"])


if __name__ == "__main__":
    unittest.main()
