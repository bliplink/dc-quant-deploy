import json
import tempfile
import unittest
from pathlib import Path

from submit_qualified_strategy_repairs import qualified_rows, selected_repairs


class SubmitQualifiedStrategyRepairsTest(unittest.TestCase):
    def qualified_metrics(self):
        return {
            "executionModelVersion": "v4_non_overlapping_walk_forward",
            "strategyVersion": "v2",
            "oosPass": 1,
            "tradeCount": 23,
            "profitFactor": 2.1,
            "maxDrawdownPct": 0.02,
            "totalPnl": 500,
            "feeAdjustedValidatePnl": 300,
            "feeAdjustedForwardPnl": 150,
            "minForwardContribution": 0.2,
        }

    def test_only_strictly_qualified_rows_are_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text(json.dumps({"results": [
                {"strategyName": "good", "metrics": self.qualified_metrics()},
                {"strategyName": "error", "executionError": True, "metrics": {}},
                {"strategyName": "bad", "metrics": {}},
            ]}), encoding="utf-8")
            rows = qualified_rows([path])
        self.assertEqual(["good"], list(rows))

    def test_rejects_unqualified_or_version_mismatch(self):
        seed = {"strategies": [{
            "strategyName": "good", "sourceStrategyVersion": "v1", "request": {},
        }]}
        rows = {"good": {"metrics": self.qualified_metrics()}}
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            selected_repairs(seed, rows, ["good"])
        with self.assertRaisesRegex(ValueError, "not locally qualified"):
            selected_repairs(seed, rows, ["missing"])


if __name__ == "__main__":
    unittest.main()
