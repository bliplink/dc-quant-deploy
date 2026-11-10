import unittest

import numpy as np
import pandas as pd

from recovery.train_execution_path_models import execution_features, path_label, training_samples


class ExecutionPathModelsTest(unittest.TestCase):
    def bars(self, size=400):
        return np.tile([100., 100.2, 99.8, 100.], (size, 1))

    def test_stop_wins_same_bar_and_fill_bar_cannot_exit(self):
        prices = self.bars()
        prices[1] = [100, 150, 50, 100]
        prices[2] = [100, 104, 98, 100]
        for side in (1, -1):
            result = path_label(prices, 0, 1., side)
            self.assertEqual((2, 'stop'), result[1:])
            self.assertLess(result[0], 0)

    def test_unfilled_and_censored_are_not_labelled_zero_profit(self):
        prices = self.bars()
        self.assertIsNone(path_label(prices, 0, 1., 1))
        prices[1] = [101, 102, 101, 101.5]
        prices[2] = [100, 104, 99, 103]
        self.assertIsNone(path_label(prices, 0, 1., 1))

    def test_close_based_trailing_only_affects_following_bar(self):
        prices = self.bars()
        prices[2] = [100, 100.9, 99.7, 100.7]
        prices[3] = [100.7, 100.8, 100.2, 100.4]
        net, end, reason = path_label(prices, 0, 1., 1)
        self.assertEqual((3, 'stop'), (end, reason))
        self.assertGreater(net, 0)

    def frame(self):
        index = np.arange(14000)
        close = 100 + np.sin(index / 9.) * 2
        return pd.DataFrame({'time': pd.date_range('2024-08-10', periods=len(index), freq='15min', tz='UTC'),
            'open': close - .1, 'high': close + .6, 'low': close - .6, 'close': close,
            'volume': 100 + index % 13})

    def test_features_are_identical_in_the_live_200_bar_window(self):
        frame = self.frame()
        full, _ = execution_features(frame)
        for end in (199, 399, 1101):
            rolling, _ = execution_features(frame.iloc[end - 199:end + 1].reset_index(drop=True))
            np.testing.assert_allclose(full[end], rolling[-1], atol=1e-9)

    def test_labels_cannot_cross_validation_boundary(self):
        frame = self.frame()
        for side in (1, -1):
            x, y, observed = training_samples(frame, side)
            self.assertEqual(18, x.shape[1])
            self.assertTrue(np.isfinite(y).all())
            for start, end, _ in observed:
                self.assertLess(frame.iloc[start + 96]['time'], pd.Timestamp('2024-12-15', tz='UTC'))
                self.assertLessEqual(end, start + 96)


if __name__ == '__main__':
    unittest.main()
