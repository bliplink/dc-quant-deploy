import json
import tempfile
import unittest
from pathlib import Path

from submit_qualified_strategy_repairs import (
    qualified_rows,
    revalidation_request,
    selected_repairs,
)


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
            "beginDate": "2025-10-08",
            "endDate": "2026-10-08",
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

    def test_builds_same_logic_revalidation_request_with_local_window(self):
        item = {
            "sourceStrategyVersion": "v2",
            "request": {
                "developmentMode": "IMPORT",
                "parentVersion": "",
                "validationOnly": True,
                "optimizationProfile": {
                    "backtestBeginDate": "2025-01-01",
                    "backtestEndDate": "2026-01-01",
                    "randomSeed": 7,
                },
            },
        }
        request = revalidation_request(item, {"metrics": self.qualified_metrics()})
        self.assertEqual("REVALIDATE", request["developmentMode"])
        self.assertEqual("v2", request["parentVersion"])
        self.assertNotIn("validationOnly", request)
        self.assertEqual("2025-10-08", request["optimizationProfile"]["backtestBeginDate"])
        self.assertEqual("2026-10-08", request["optimizationProfile"]["backtestEndDate"])
        self.assertEqual(7, request["optimizationProfile"]["randomSeed"])

    def test_revalidation_requires_parent_version_and_window(self):
        with self.assertRaisesRegex(ValueError, "sourceStrategyVersion"):
            revalidation_request({"request": {}}, {"metrics": self.qualified_metrics()})
        with self.assertRaisesRegex(ValueError, "beginDate and endDate"):
            revalidation_request(
                {"sourceStrategyVersion": "v2", "request": {}},
                {"metrics": {"beginDate": "2025-10-08"}},
            )


if __name__ == "__main__":
    unittest.main()
