import copy
import unittest

from recovery.supplement_temporal_holdout import require_passing_fixed_primary


class SupplementTemporalHoldoutTest(unittest.TestCase):
    def fixture(self):
        envelope = {'productionWrite': False, 'result': {
            'qualified': True, 'holdout': {'passed': True},
            'executionModelVersion': 'v4_non_overlapping_walk_forward',
            'beginDate': '2024-12-15', 'endDate': '2025-10-12', 'oosPass': 1,
            'tradeCount': 23, 'profitFactor': 1.65, 'maxDrawdownPct': 0.02,
            'feeAdjustedValidatePnl': 349, 'feeAdjustedForwardPnl': 338,
            'forwardContribution': 0.60, 'minForwardContribution': 0.20,
            'sliceResults': [{}, {}, {}], 'optimizationTrials': [{'paramSetJson': '{}'}]}}
        return {'qualified': True}, envelope, {'strategies': [{'request': {
            'parameterSchema': {}, 'defaultParameters': {}}}]}, {
                'primary_begin': '2024-12-15', 'primary_end_inclusive': '2025-10-12'}

    def test_completed_fixed_pass_can_add_a_stricter_holdout_without_replaying_primary(self):
        require_passing_fixed_primary(*self.fixture())

    def test_original_financial_failures_and_failed_legacy_holdout_cannot_be_relabelled(self):
        for key, value in [('qualified', False), ('oosPass', 0), ('tradeCount', 19),
                           ('profitFactor', 1.19), ('maxDrawdownPct', 0.151),
                           ('feeAdjustedValidatePnl', 0), ('feeAdjustedForwardPnl', -1),
                           ('forwardContribution', 0.19), ('endDate', '2025-10-13')]:
            record, envelope, seed, protocol = self.fixture()
            envelope['result'][key] = value
            with self.assertRaises(ValueError):
                require_passing_fixed_primary(record, envelope, seed, protocol)
        record, envelope, seed, protocol = self.fixture()
        envelope['result']['holdout']['passed'] = False
        with self.assertRaises(ValueError):
            require_passing_fixed_primary(record, envelope, seed, protocol)

    def test_fitted_parameters_cannot_silently_use_fixed_default_holdout(self):
        for request in ({'parameterSchema': {'parameters': [{'name': 'riskProfile'}]}},
                        {'defaultParameters': {'riskProfile': 0}}):
            record, envelope, seed, protocol = self.fixture()
            seed['strategies'][0]['request'].update(request)
            with self.assertRaises(ValueError):
                require_passing_fixed_primary(record, envelope, seed, protocol)
        record, envelope, seed, protocol = self.fixture()
        envelope['result']['optimizationTrials'][0]['paramSetJson'] = '{"riskProfile":2}'
        with self.assertRaises(ValueError):
            require_passing_fixed_primary(record, envelope, seed, protocol)


if __name__ == '__main__':
    unittest.main()
