#!/usr/bin/env python3

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_strategy_repair_seed import build, candidates, sample_floor


class StrategyRepairSeedTest(unittest.TestCase):
    def test_candidates_expand_around_default_and_keep_existing(self):
        self.assertEqual([5, 7, 8, 10, 12, 13], candidates("lookback", 10, [5, 10]))
        self.assertIn(0.7, candidates("threshold", 1.0))
        self.assertIn(1.3, candidates("threshold", 1.0))

    def test_build_only_includes_failed_and_sets_sample_floor(self):
        seed = {"strategies": [
            {"strategyName": "failed", "sourceStrategyVersion": "v1", "symbol": "BTCUSDT",
             "scene": "breakout", "text": "15m", "request": {
                 "defaultParameters": {"lookback": 20, "firstStepPct": 0.5},
                 "parameterSchema": {}, "optimizationProfile": {}}},
            {"strategyName": "passed", "sourceStrategyVersion": "v1", "symbol": "ETHUSDT",
             "scene": "range", "text": "15m", "request": {"defaultParameters": {}}},
        ]}
        batch = {"results": [
            {"strategyName": "failed", "qualified": False, "executionError": False,
             "qualificationReason": "too_few_trades", "metrics": {}},
            {"strategyName": "passed", "qualified": True, "executionError": False},
        ]}
        repaired, queue = build(seed, batch)
        self.assertEqual(1, repaired["summary"]["repairCount"])
        request = repaired["strategies"][0]["request"]
        self.assertEqual(20, request["optimizationProfile"]["minFitTradesPerSlice"])
        self.assertEqual("FEE_ADJUSTED_PROFIT_FIRST", request["optimizationProfile"]["objective"])
        self.assertEqual(["lookback"], [row["name"] for row in request["parameterSchema"]["parameters"]])
        self.assertEqual(1, queue["summary"]["queuedCount"])

    def test_scene_sample_floors(self):
        self.assertEqual(10, sample_floor("range"))
        self.assertEqual(20, sample_floor("reversal"))
        self.assertEqual(16, sample_floor("trend"))


if __name__ == "__main__":
    unittest.main()
