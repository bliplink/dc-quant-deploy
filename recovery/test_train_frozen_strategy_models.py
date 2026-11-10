import unittest

from recovery.train_frozen_strategy_models import feature_matrix, samples, restored_prediction


class FrozenTrainingBoundaryTest(unittest.TestCase):
    @staticmethod
    def frame():
        import numpy as np
        import pandas as pd
        close = 100 + np.sin(np.arange(600) / 13) + np.arange(600) * 0.002
        return pd.DataFrame({'time': pd.date_range('2024-12-10', periods=600, freq='15min', tz='UTC'),
            'open': close - 0.04, 'high': close + 0.2, 'low': close - 0.2,
            'close': close, 'volume': 100 + np.arange(600) % 11})

    def test_training_labels_never_enter_existing_validation_period(self):
        import pandas as pd
        frame = self.frame()
        x, y, indices = samples(frame)
        self.assertGreater(len(y), 0)
        self.assertEqual(x.shape[1], 12)
        self.assertTrue((frame.iloc[indices + 16]['time'] < pd.Timestamp('2024-12-15', tz='UTC')).all())
        self.assertTrue(all(b - a >= 16 for a, b in zip(indices, indices[1:])))

    def test_feature_vectors_match_two_hundred_bar_live_capacity(self):
        import numpy as np
        frame = self.frame()
        full, full_vol = feature_matrix(frame)
        for i in (199, 276, 355, 511):
            live, live_vol = feature_matrix(frame.iloc[i - 199:i + 1])
            np.testing.assert_allclose(full[i], live[-1], rtol=1e-10, atol=1e-10)
            self.assertAlmostEqual(full_vol[i], live_vol[-1], places=12)

    def test_tree_export_uses_sklearn_float32_split_semantics(self):
        import numpy as np
        model = {'algorithm': 'boosted_tree', 'initial': 0.1, 'learning_rate': 0.5,
            'trees': [[[0, 0.25, 1, 2, 0], [-1, 0, -1, -1, -0.3], [-1, 0, -1, -1, 0.7]]]}
        actual = restored_prediction(model, np.array([[0.2500000001], [0.5]]))
        np.testing.assert_allclose(actual, [-0.05, 0.45])

    def test_numpy_scalar_promotion_must_not_round_double_tree_threshold(self):
        import numpy as np
        model = {'algorithm': 'boosted_tree', 'initial': 0.0, 'learning_rate': 1.0,
            'trees': [[[0, 1.0 - 2**-25, 1, 2, 0], [-1, 0, -1, -1, -1], [-1, 0, -1, -1, 1]]]}
        self.assertEqual(restored_prediction(model, np.array([[1.0]]))[0], 1)


if __name__ == '__main__':
    unittest.main()
