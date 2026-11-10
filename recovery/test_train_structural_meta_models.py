import unittest

import numpy as np

from recovery.train_structural_meta_models import balanced_year_weights, event_samples
from recovery import test_train_execution_path_models as fixtures


class StructuralMetaModelsTest(unittest.TestCase):
    def test_each_year_gets_equal_total_weight(self):
        years = np.asarray([2022, 2022, 2023, 2024, 2024, 2024])
        weights = balanced_year_weights(years)
        np.testing.assert_allclose([2, 2, 2], [weights[years == year].sum() for year in (2022, 2023, 2024)])

    def test_missing_year_is_unavailable_not_a_fallback(self):
        with self.assertRaises(ValueError): balanced_year_weights([2022, 2023])

    def test_events_must_match_frozen_bar_timestamp(self):
        frame = fixtures.ExecutionPathModelsTest().frame()
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            event_samples(frame, [{'family': 'AuctionValueRejectionHypothesis', 'side': 1, 'index': 400, 'time': 0}])

    def test_event_label_cannot_enter_validation_data(self):
        frame = fixtures.ExecutionPathModelsTest().frame()
        i = 12500
        event = {'family': 'AuctionValueRejectionHypothesis', 'side': 1,
                 'index': i, 'time': int(frame.iloc[i]['time'].timestamp() * 1000)}
        self.assertEqual({}, event_samples(frame, [event]))


if __name__ == '__main__':
    unittest.main()
