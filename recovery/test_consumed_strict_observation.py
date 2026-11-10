"""Replay only the pure qualification arithmetic, never any financial window."""
import json
from pathlib import Path
import unittest

from recovery.strict_primary_admission import adjudicate_primary


class ConsumedStrictObservationTest(unittest.TestCase):
    def test_positive_primary_and_holdout_do_not_override_existing_contribution_floor(self):
        path = Path(__file__).with_name('snapshots') / 'fit-risk-strict-rejection-link-20261111.json'
        observation = json.loads(path.read_text(encoding='utf-8'))
        self.assertTrue(observation['raw_local_qualified'])
        self.assertTrue(observation['holdout']['passed'])
        actual = adjudicate_primary(observation['primary_result'])
        for key, expected in observation['strict_admission'].items():
            self.assertEqual(expected, actual[key])
        self.assertFalse(actual['qualified'])
        self.assertEqual(0, observation['server_submission_count'])
        self.assertFalse(observation['financial_replay_performed'])
        self.assertFalse(observation['financial_outputs_modified'])


if __name__ == '__main__': unittest.main()
