#!/usr/bin/env python3

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from summarize_local_strategy_batches import build_summary, evaluate


class LocalStrategyBatchSummaryTest(unittest.TestCase):
    def test_forward_contribution_uses_validate_pnl_for_legacy_local_result(self):
        result = evaluate({
            "executionModelVersion": "v4_non_overlapping_walk_forward",
            "oosPass": 1,
            "tradeCount": 25,
            "profitFactor": 1.5,
            "maxDrawdownPct": 0.05,
            "validatePnl": 100,
            "feeAdjustedValidatePnl": 80,
            "feeAdjustedForwardPnl": 25,
        })
        self.assertTrue(result["qualified"])
        self.assertEqual(0.25, result["forwardContribution"])

    def test_corrected_batch_overrides_same_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            corrected = root / "corrected.json"
            common = {
                "executionModelVersion": "v4_non_overlapping_walk_forward",
                "oosPass": 1,
                "tradeCount": 25,
                "profitFactor": 1.5,
                "maxDrawdownPct": 0.05,
                "validatePnl": 100,
                "feeAdjustedValidatePnl": 80,
            }
            baseline.write_text(json.dumps({"results": [{
                "strategyName": "one", "symbol": "BTCUSDT", "scene": "range",
                "metrics": {**common, "feeAdjustedForwardPnl": 25},
            }]}), encoding="utf-8")
            corrected.write_text(json.dumps({"results": [{
                "strategyName": "one", "symbol": "BTCUSDT", "scene": "range",
                "metrics": {**common, "feeAdjustedForwardPnl": -1},
            }]}), encoding="utf-8")

            summary = build_summary(baseline, corrected)

        self.assertEqual(1, summary["summary"]["strategyCount"])
        self.assertEqual(0, summary["summary"]["qualifiedCount"])
        self.assertEqual("fee_adjusted_forward_not_positive",
                         summary["results"][0]["qualificationReason"])


if __name__ == "__main__":
    unittest.main()
