import copy
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-robot-capacity.py'))
REQUIRE = CAPACITY['require_client_ack_policy']


class CapacityClientAckPolicyTest(unittest.TestCase):
    def voters(self, mode):
        return [{
            'Name': f'/mac-demo-20261112-073320-{service}-{slot}-hostready',
            'State': {'Running': True},
            'Config': {'Labels': {'dc.common.jar.sha256': 'fixture-sha',
                                  'otc.common.client_ack_policy': mode},
                       'Env': ['JAVA_TOOL_OPTIONS=-Dcommon.certified.clientAckPolicy=' + mode]},
        } for service in ('order', 'trade') for slot in 'ab']

    def require(self, voters, mode):
        release = {'common_sha256': 'fixture-sha', 'client_ack_policy': mode}
        with patch.dict(CAPACITY['FRESH'], selected_client_ack_policy=lambda images, selected: selected), \
                patch.object(CAPACITY['subprocess'], 'check_output', return_value=json.dumps(voters)):
            return REQUIRE(Path('/fixture/mac-demo-20261112-073320'), release)

    def test_all_four_voters_must_use_the_declared_async_contract(self):
        mode = 'LOCAL_DURABLE_ASYNC'
        voters = self.voters(mode)
        self.assertEqual(mode, self.require(voters, mode))
        for options in ([], ['JAVA_OPTS=-Dcommon.certified.clientAckPolicy=STRICT_QUORUM'],
                        ['JAVA_OPTS=-Dcommon.certified.clientAckPolicy=LOCAL_DURABLE_ASYNC',
                         'JAVA_TOOL_OPTIONS=-Dcommon.certified.clientAckPolicy=LOCAL_DURABLE_ASYNC']):
            changed = copy.deepcopy(voters)
            changed[3]['Config']['Env'] = options
            with self.subTest(options=options), self.assertRaises(RuntimeError):
                self.require(changed, mode)

    def test_old_strict_default_and_explicit_strict_are_both_supported(self):
        mode = 'STRICT_QUORUM'
        voters = self.voters(mode)
        self.assertEqual(mode, self.require(voters, mode))
        for voter in voters:
            voter['Config']['Labels'].pop('otc.common.client_ack_policy')
            voter['Config']['Env'] = ['JAVA_OPTS=-Xmx512m']
        self.assertEqual(mode, self.require(voters, mode))

    def test_wrong_jar_labels_names_and_stopped_voters_are_rejected(self):
        mode = 'LOCAL_DURABLE_ASYNC'
        original = self.voters(mode)
        changes = [({'dc.common.jar.sha256': 'other'}, None),
                   ({'otc.common.client_ack_policy': 'STRICT_QUORUM'}, None),
                   ({}, ('Name', '/other-voter')),
                   ({}, ('State', {'Running': False}))]
        for labels, field in changes:
            voters = copy.deepcopy(original)
            voters[0]['Config']['Labels'].update(labels)
            if field:
                voters[0][field[0]] = field[1]
            with self.subTest(change=(labels, field)), self.assertRaises(RuntimeError):
                self.require(voters, mode)
        with self.assertRaises(RuntimeError):
            self.require(original[:3], mode)
        original[0]['Config']['Labels'].pop('otc.common.client_ack_policy')
        with self.assertRaises(RuntimeError):
            self.require(original, mode)


if __name__ == '__main__':
    unittest.main()
