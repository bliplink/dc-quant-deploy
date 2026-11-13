import copy
import hashlib
from pathlib import Path
import runpy
import unittest


CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1]
                           / 'scripts/reconcile-mac-demo-execution-capacity.py'))


class ExecutionReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.location, self.run = 'TEST01', '1234abcd'
        prefix = 'T554EXEC-' + self.run + '-'
        self.client = prefix + '0'
        match = '\x1f'.join([self.location, CHECK['SYMBOL'], 'maker-order', 'taker-order', '0'])
        self.ids = {role: 'E' + hashlib.sha256((match + '\x1f' + role).encode()).hexdigest()[:30]
                    for role in ['maker', 'taker']}
        self.data = {
            'orders': [[prefix + 'MAKER', 'maker-order', 'maker-user', 'Cancelled'],
                       [self.client, 'taker-order', 'taker-user', 'Filled']],
            'executions': [[prefix + 'MAKER', self.ids['maker'], '.001'],
                           [self.client, self.ids['taker'], '.001']],
            'positions': [['maker-user', '0', '.001'], ['taker-user', '.001', '0']],
            'public': [{'execID': self.ids['maker'], 'count()': 1, 'sum(quantity)': '.001'}],
            'observed': {self.client: self.ids['taker']},
        }

    def verify(self, data):
        return CHECK['verify_rows'](self.location, self.run, **data)

    def test_one_public_identity_for_each_exact_customer_pair(self):
        for role in ['maker', 'taker']:
            self.data['public'][0]['execID'] = self.ids[role]
            self.assertEqual(1, self.verify(self.data)['physical_public_trades'])

    def test_missing_duplicate_or_two_public_sides_cannot_pass(self):
        for public in [[], self.data['public'] * 2,
                       [{'execID': self.ids['maker'], 'count()': 2, 'sum(quantity)': '.002'}],
                       self.data['public'] + [{'execID': self.ids['taker'], 'count()': 1,
                                               'sum(quantity)': '.001'}]]:
            data = copy.deepcopy(self.data)
            data['public'] = public
            with self.subTest(public=public), self.assertRaises(AssertionError):
                self.verify(data)

    def test_private_identity_and_position_must_match_the_original_fills(self):
        for key, value in [('observed', {self.client: 'another-execution'}),
                           ('positions', [['maker-user', '0', '.002'], ['taker-user', '.001', '0']]),
                           ('executions', self.data['executions'] * 2)]:
            data = copy.deepcopy(self.data)
            data[key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError):
                self.verify(data)


if __name__ == '__main__':
    unittest.main()
