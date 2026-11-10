import unittest

import numpy as np

from recovery.train_structural_expectancy_models import fit_expectancy
from recovery.train_frozen_strategy_models import restored_prediction


class StructuralExpectancyModelsTest(unittest.TestCase):
    def test_rare_large_losses_cannot_be_ignored_as_outliers(self):
        x = np.zeros((100, 18)); y = np.array([1.] * 90 + [-10.] * 10)
        fit, model = fit_expectancy(x, y, np.ones(len(y)))
        self.assertEqual('squared_error', fit.loss)
        self.assertLess(fit.predict(x[:1])[0], 0)
        self.assertAlmostEqual(-.1, fit.predict(x[:1])[0], places=10)
        np.testing.assert_allclose(fit.predict(x), restored_prediction(model, x), atol=1e-12)

    def test_weighted_mean_includes_full_payoff_sizes(self):
        x = np.zeros((100, 18)); y = np.array([1.] * 50 + [-2.] * 50)
        weights = np.array([1.] * 50 + [3.] * 50)
        fit, model = fit_expectancy(x, y, weights)
        self.assertAlmostEqual(np.average(y, weights=weights), model['initial'], places=12)
        self.assertAlmostEqual(-1.25, fit.predict(x[:1])[0], places=10)

    def test_nonfinite_labels_are_rejected_not_silently_dropped(self):
        y = np.ones(100); y[0] = np.nan
        with self.assertRaises(ValueError): fit_expectancy(np.zeros((100, 18)), y, np.ones(100))


if __name__ == '__main__':
    unittest.main()
