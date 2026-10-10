#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_strategy_backtest import resolve_window_days
from prepare_local_strategy_queue import qualification_reason


class LocalStrategyBacktestTest(unittest.TestCase):
    def test_production_scene_windows(self):
        defaults = SimpleNamespace(
            fit_window_days=None, validate_window_days=None, forward_window_days=None)
        self.assertEqual((90, 30, 14), resolve_window_days(
            {"scene": "range", "text": "15m", "request": {}}, defaults))
        self.assertEqual((120, 20, 10), resolve_window_days(
            {"scene": "breakout", "text": "15m", "request": {}}, defaults))
        self.assertEqual((120, 20, 10), resolve_window_days(
            {"scene": "reversal", "text": "15m", "request": {}}, defaults))
        self.assertEqual((120, 30, 14), resolve_window_days(
            {"scene": "trend", "text": "15m", "request": {}}, defaults))

    def test_explicit_window_override_wins(self):
        explicit = SimpleNamespace(
            fit_window_days=70, validate_window_days=21, forward_window_days=7)
        self.assertEqual((70, 21, 7), resolve_window_days(
            {"scene": "range", "text": "15m", "request": {}}, explicit))

    def test_queue_gate_includes_forward_contribution(self):
        metrics = {
            "oosPass": 1,
            "tradeCount": 25,
            "profitFactor": 1.5,
            "maxDrawdownPct": 0.05,
            "validatePnl": 100,
            "feeAdjustedValidatePnl": 80,
            "feeAdjustedForwardPnl": 10,
        }
        self.assertEqual("forward_contribution_too_low", qualification_reason(metrics))
        metrics["feeAdjustedForwardPnl"] = 25
        self.assertEqual("qualified", qualification_reason(metrics))


if __name__ == "__main__":
    unittest.main()
