import unittest
import numpy as np

from recovery.formal_payoff_labels import adjusted_return, path_label, trailing_stop


class FormalPayoffLabelTest(unittest.TestCase):
    def bars(self):
        return np.tile([100., 100.1, 99.9, 100.], (100, 1))

    def test_default_cost_matches_formal_entry_capital_fees_and_notional_stress(self):
        self.assertAlmostEqual(.03 - .0007 - .0004 - .0005 * 1.03,
                               adjusted_return(100, 103, 1), places=12)
        self.assertAlmostEqual(.03 - .0007 - .0004 - .0005 * .97,
                               adjusted_return(100, 97, -1), places=12)
        self.assertLess(adjusted_return(100, 98.5, 1), 0)

    def test_step_boundary_uses_formal_difference_then_divide_order(self):
        self.assertEqual(102., trailing_stop(100., 102.5, 98.5, 1, 2., .5))
        self.assertAlmostEqual(102.3, trailing_stop(100., 102.5, 98.5, 1, .5, .2))
        self.assertEqual(98., trailing_stop(100., 97.5, 101.5, -1, 2., .5))

    def test_fill_bar_has_no_risk_exit_and_stop_wins_collision(self):
        prices = self.bars()
        prices[1] = [100, 110, 90, 100]
        prices[2] = [100, 104, 96, 100]
        for side in (-1, 1):
            net, end, reason = path_label(prices, 0, 1., side)
            self.assertEqual((2, 'stop'), (end, reason))
            self.assertLess(net, 0)

    def test_trail_is_frozen_and_activates_only_on_following_bar(self):
        prices = self.bars()
        prices[2] = [100, 102.6, 99.9, 102.5]
        prices[3] = [102.5, 102.6, 101.9, 102.1]
        net, end, reason = path_label(prices, 0, 1., 1)
        self.assertEqual((3, 'stop'), (end, reason))
        self.assertAlmostEqual(adjusted_return(100, 102, 1), net)

    def test_unfilled_or_censored_is_not_a_fake_zero_profit_observation(self):
        prices = self.bars()
        self.assertIsNone(path_label(prices, 0, 1., 1))
        prices[1] = [101, 102, 101, 101]
        prices[2] = [100, 104, 99, 103]
        self.assertIsNone(path_label(prices, 0, 1., 1))


if __name__ == '__main__':
    unittest.main()
