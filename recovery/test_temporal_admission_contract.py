import copy
import unittest

from recovery.temporal_admission_contract import (
    require_temporally_isolated_admission, temporal_overlap_evidence,
)


class TemporalAdmissionTest(unittest.TestCase):
    def envelope(self):
        slices = []
        from datetime import date, timedelta
        for i in range(4):
            first = date(2024, 12, 15) + timedelta(days=44 * i)
            slices.append({'sliceNo': i + 1, 'fitBegin': str(first), 'fitEnd': str(first + timedelta(days=119)),
                'validateBegin': str(first + timedelta(days=120)), 'validateEnd': str(first + timedelta(days=149)),
                'forwardBegin': str(first + timedelta(days=150)), 'forwardEnd': str(first + timedelta(days=163))})
        return {'productionWrite': False, 'sourceSha256': 'frozen_source', 'result': {
            'admissionSchema': 'local_temporal_holdout_v2', 'beginDate': '2024-12-15', 'endDate': '2025-10-12',
            'sliceResults': slices, 'selectedParameters': {'riskProfile': 2},
            'bestParamSetJson': '{"riskProfile":2}', 'holdout': {
                'beginDate': '2025-10-13', 'endDate': '2025-12-13', 'lockedParameters': {'riskProfile': 2},
                'parameterPolicy': 'frozen_pre_holdout_representative', 'sourceSha256': 'frozen_source',
                'optimizerInvocations': 0, 'fitInvocations': 0}}}

    def test_disjoint_complete_period_and_locked_profile_are_required(self):
        audit = require_temporally_isolated_admission(self.envelope())
        self.assertEqual(62, audit['holdout_calendar_days'])

    def test_fixed_sources_also_need_isolation_but_lock_an_empty_parameter_map(self):
        envelope = self.envelope()
        envelope['result']['selectedParameters'] = {}
        envelope['result']['bestParamSetJson'] = '{}'
        envelope['result']['holdout']['lockedParameters'] = {}
        require_temporally_isolated_admission(envelope, require_risk_profile=False)
        with self.assertRaises(ValueError):
            require_temporally_isolated_admission(envelope)

    def test_overlapping_primary_validation_phases_and_noninteger_profiles_are_rejected(self):
        envelope = self.envelope()
        envelope['result']['sliceResults'][1]['validateBegin'] = '2025-05-27'
        with self.assertRaises(ValueError):
            require_temporally_isolated_admission(envelope)
        for value in (True, 2.5, '2', -1, 4):
            envelope = self.envelope()
            envelope['result']['selectedParameters'] = {'riskProfile': value}
            with self.assertRaises(ValueError):
                require_temporally_isolated_admission(envelope)

    def test_existing_legacy_slices_expose_real_august_holdout_overlap(self):
        evidence = temporal_overlap_evidence(self.envelope()['result'], '2025-08-12', '2025-10-12')
        self.assertFalse(evidence['fully_disjoint'])
        self.assertEqual({'fit', 'validate', 'forward'}, {row['phase'] for row in evidence['overlaps']})

    def test_temporal_leak_shortening_skips_and_missing_schema_fail_closed(self):
        original = self.envelope()
        for key, value in [('beginDate', '2025-08-12'), ('beginDate', '2025-10-14'),
                           ('endDate', '2025-12-12')]:
            envelope = copy.deepcopy(original)
            envelope['result']['holdout'][key] = value
            with self.assertRaises(ValueError):
                require_temporally_isolated_admission(envelope)
        envelope = copy.deepcopy(original)
        envelope['result'].pop('admissionSchema')
        with self.assertRaises(ValueError):
            require_temporally_isolated_admission(envelope)

    def test_default_parameter_substitution_refitting_or_source_change_are_rejected(self):
        original = self.envelope()
        for key, value in [('lockedParameters', {'riskProfile': 0}), ('optimizerInvocations', 1),
                           ('fitInvocations', 1), ('sourceSha256', 'other'), ('parameterPolicy', 'default_params')]:
            envelope = copy.deepcopy(original)
            envelope['result']['holdout'][key] = value
            with self.assertRaises(ValueError):
                require_temporally_isolated_admission(envelope)


if __name__ == '__main__':
    unittest.main()
