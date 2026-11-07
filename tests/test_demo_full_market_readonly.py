#!/usr/bin/env python3
"""T542 market-data/K-line live acceptance contract tests; no network required."""
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).with_name("check_demo_full_market_readonly.py")
spec=importlib.util.spec_from_file_location("t542_full_market",path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class T542MarketAcceptanceTests(unittest.TestCase):
    def test_valid_ohlc_epoch_and_volume(self):
        rows=["160500,1794038700000,76111,76120,76034.9,76110,0.001,76.11",
              "161000,1794039000000,76110,76130,76090,76125,0.002,152.2"]
        self.assertEqual(m.parse_bars(rows,"5M"),(2,1794039000000))

    def test_missing_history_is_no_go(self):
        with self.assertRaisesRegex(ValueError,"KLINE_NO_HISTORY"):
            m.parse_bars([],"5M")

    def test_duplicate_timestamp_is_rejected(self):
        row="160500,1794038700000,76111,76120,76034.9,76110,0.001"
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            m.parse_bars([row,row],"5M")

    def test_bad_price_candle_invariant_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"OHLC_INVARIANT"):
            m.parse_bars(["160500,1794038700000,76111,76109,76034.9,76110,0.01"],"5M")

    def test_negative_volume_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"OHLC_INVARIANT"):
            m.parse_bars(["160500,1794038700000,76111,76120,76034.9,76110,-0.01"],"5M")

    def test_old_seconds_not_milliseconds_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"EPOCH"):
            m.parse_bars(["160500,1794038700,76111,76120,76034.9,76110,0.01"],"5M")


if __name__ == "__main__":
    unittest.main()