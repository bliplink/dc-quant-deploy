import copy
import unittest

from recovery.strict_primary_admission import adjudicate_primary, require_primary_admission


class StrictPrimaryAdmissionTest(unittest.TestCase):
    def result(self, **changes):
        return dict(executionModelVersion='v4_non_overlapping_walk_forward', oosPass=1,
            tradeCount=30, profitFactor=1.5, maxDrawdownPct=.05, feeAdjustedValidatePnl=100,
            feeAdjustedForwardPnl=200, totalPnl=1000, minForwardContribution=0, **changes)

    def test_zero_or_missing_dto_requirement_does_not_waive_existing_floor(self):
        result = self.result()
        result.update(totalPnl=653.000580, feeAdjustedForwardPnl=10.104428)
        for value in (None, 0, '0.00'):
            result['minForwardContribution'] = value
            audit = adjudicate_primary(result)
            self.assertFalse(audit['qualified'])
            self.assertEqual('forward_contribution_too_low', audit['reason'])
            self.assertEqual('0.015474', audit['forward_contribution_ratio'])
            self.assertEqual('0.20', audit['required_forward_contribution'])
            with self.assertRaisesRegex(ValueError, 'forward_contribution_too_low'):
                require_primary_admission(result)

    def test_exact_existing_boundary_and_higher_declared_requirements(self):
        self.assertTrue(adjudicate_primary(self.result())['qualified'])
        self.assertFalse(adjudicate_primary(self.result(), {'minForwardContribution': .25})['qualified'])
        result = self.result()
        result['minForwardContribution'] = .30
        self.assertFalse(adjudicate_primary(result)['qualified'])
        self.assertTrue(adjudicate_primary(self.result(), {'minForwardContribution': 0})['qualified'])

    def test_six_decimal_half_up_matches_existing_java_gate(self):
        result = self.result()
        result['feeAdjustedForwardPnl'] = 199.9995
        self.assertTrue(adjudicate_primary(result)['qualified'])
        result['feeAdjustedForwardPnl'] = 199.9994
        self.assertFalse(adjudicate_primary(result)['qualified'])

    def test_all_other_existing_primary_gates_remain_required(self):
        for key, value, reason in (
                ('oosPass', 0, 'oos_not_passed'), ('tradeCount', 19, 'too_few_trades'),
                ('profitFactor', 1.199999, 'profit_factor_too_low'),
                ('maxDrawdownPct', .150001, 'drawdown_too_high'),
                ('feeAdjustedValidatePnl', 0, 'fee_adjusted_validate_not_positive'),
                ('feeAdjustedForwardPnl', 0, 'fee_adjusted_forward_not_positive')):
            result = self.result()
            result[key] = value
            self.assertEqual(reason, adjudicate_primary(result)['reason'])

    def test_corrupt_metrics_and_negative_requirements_fail_closed(self):
        for value in (None, True, float('inf'), float('nan')):
            result = self.result()
            result['profitFactor'] = value
            with self.assertRaises(ValueError):
                adjudicate_primary(result)
        with self.assertRaises(ValueError):
            adjudicate_primary(self.result(), {'minForwardContribution': -1})

    def test_read_only_adjudication_never_changes_consumed_metrics(self):
        result = self.result()
        before = copy.deepcopy(result)
        audit = adjudicate_primary(result)
        self.assertEqual(before, result)
        self.assertEqual(0, result['minForwardContribution'])
        self.assertFalse(audit['financial_outputs_modified'])
        self.assertFalse(audit['financial_replay_performed'])


if __name__ == '__main__':
    unittest.main()
