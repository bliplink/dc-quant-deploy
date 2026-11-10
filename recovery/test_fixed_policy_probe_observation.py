"""Keep software-only gate evidence distinct from financial qualification and release."""
import hashlib
import json
from pathlib import Path
import unittest


class FixedPolicyProbeObservationTest(unittest.TestCase):
    def test_actual_unchanged_probe_snapshot_has_no_financial_or_publish_claim(self):
        path = Path(__file__).with_name('snapshots') / 'fixed-policy-publication-gate-observation-20261111.json'
        self.assertEqual('ea549ee820e0f675912d0372c40c98fd5dc4efc63f747ea3d6e2b93bde398e8f', hashlib.sha256(path.read_bytes()).hexdigest())
        data = json.loads(path.read_text())
        self.assertTrue(data['synthetic_summary_only'])
        self.assertFalse(data['financial_replay_performed'])
        self.assertFalse(data['production_write'])
        self.assertEqual(0, data['publish_or_dao_invocations'])
        self.assertFalse(data['optimization_supported'])
        self.assertFalse(data['expects_optimization_evidence'])
        self.assertEqual([{}], data['default_param_sets'])
        self.assertEqual('', data['global_precondition_reason'])
        self.assertEqual('best param set missing', data['fixed_empty_parameter_reason'])
        self.assertTrue(data['control_is_not_a_proposed_dummy_parameter_workaround'])
        self.assertEqual('fee adjusted forward pnl <= 0', data['negative_forward_reason'])
        self.assertEqual('oos gate not passed', data['failed_oos_reason'])
        self.assertEqual('forward contribution below threshold', data['low_contribution_reason'])
        self.assertEqual('scene fixture rejected', data['failed_scene_reason'])


if __name__ == '__main__': unittest.main()
