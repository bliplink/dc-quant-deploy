import unittest

import numpy as np

from recovery.train_regime_consensus_models import median_prediction


class RegimeConsensusModelsTest(unittest.TestCase):
    def models(self):
        return [{'group': 'value', 'algorithm': 'ridge', 'side': 1, 'year': year,
                 'coefficients': [0, 0], 'intercept': prediction}
                for year, prediction in ((2022, -1), (2023, .4), (2024, 10))]

    def test_median_not_bull_year_mean_or_best_year_selection(self):
        result = median_prediction(self.models(), np.zeros((2, 2)), 'value', 'ridge', 1)
        np.testing.assert_allclose([.4, .4], result)

    def test_missing_regime_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, 'all three'):
            median_prediction(self.models()[:-1], np.zeros((1, 2)), 'value', 'ridge', 1)


if __name__ == '__main__':
    unittest.main()
