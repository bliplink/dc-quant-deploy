import unittest

import strategy_inventory_snapshot as snapshot


class StrategyInventorySnapshotTest(unittest.TestCase):
    def test_runtime_qualification_and_separate_forward_contribution(self):
        row = {
            'oos_pass': 1,
            'trade_count': 24,
            'profit_factor': 1.5,
            'max_drawdown_pct': 0.05,
            'fee_adjusted_validate_pnl': 400.0,
            'fee_adjusted_forward_pnl': 50.0,
            'total_pnl': 500.0,
            'min_forward_contribution': 0.2,
        }
        self.assertEqual('qualified', snapshot.reason(row))
        self.assertFalse(snapshot.passes_forward_contribution(row))
        self.assertAlmostEqual(0.1, snapshot.forward_contribution_ratio(row))
        row['fee_adjusted_forward_pnl'] = 100.0
        self.assertTrue(snapshot.passes_forward_contribution(row))
        self.assertIsNone(snapshot.forward_contribution_ratio({'total_pnl': 0}))

    def test_missing_and_oos_failure_are_not_qualified(self):
        self.assertEqual('realistic_backtest_missing', snapshot.reason(None))
        self.assertFalse(snapshot.passes_forward_contribution(None))
        self.assertEqual('oos_not_passed', snapshot.reason({'oos_pass': 0}))


if __name__ == '__main__':
    unittest.main()
