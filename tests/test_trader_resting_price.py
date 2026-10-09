"""Offline resting limit price calculation regression (no live orders)."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("trader-resting-price.py")
spec = importlib.util.spec_from_file_location("trader_resting_price", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def snap(entries):
    return {"code": 0, "data": {"orderBook": {"NoMDEntries": entries}}}


class TraderRestingPriceTests(unittest.TestCase):
    def test_buy_limit_is_below_best_bid(self):
        value = module.choose_resting_bid(snap([
            {"MDEntryType": "1", "MDEntryPx": "61001.0"},
            {"MDEntryType": "0", "MDEntryPx": "61000.0"},
            {"MDEntryType": "0", "MDEntryPx": "60999.0"},
        ]))
        self.assertEqual(value, "60695.0")

    def test_lower_bid_and_custom_tick(self):
        value = module.choose_resting_bid(snap([
            {"MDEntryType": "0", "MDEntryPx": "200.13"}
        ]), tick="0.01", discount="0.01")
        self.assertEqual(value, "198.12")

    def test_missing_bids_never_assumes_a_safe_price(self):
        with self.assertRaisesRegex(ValueError, "no positive bid"):
            module.choose_resting_bid(snap([{"MDEntryType": "1", "MDEntryPx": "61001"}]))

    def test_tiny_best_bid_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "non-crossing"):
            module.choose_resting_bid(snap([{"MDEntryType": "0", "MDEntryPx": "0.01"}]))

    def test_no_negative_and_non_finite_values(self):
        with self.assertRaisesRegex(ValueError, "no positive bid"):
            module.choose_resting_bid(snap([
                {"MDEntryType": "0", "MDEntryPx": "-1"},
                {"MDEntryType": "0", "MDEntryPx": "NaN"},
            ]))


if __name__ == "__main__":
    unittest.main()
