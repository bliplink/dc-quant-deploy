import json
import tempfile
import unittest
from pathlib import Path

from recovery.run_fit_risk_scope_batch import build_queue, completed_observation, strategy_name
from recovery.verify_fit_only_risk_contract import FAMILIES, sha


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class ScopeBatchTest(unittest.TestCase):
    def test_queue_balances_all_cells_without_multiplying_risk_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof, inputs = root / 'proof', root / 'inputs'
            write(proof / 'manifest.json', {'families': FAMILIES})
            write(proof / 'audit.json', {'state': 'complete', 'source_contracts': 8,
                'profile_signal_parity_cases': 32, 'manifest_sha256': sha(proof / 'manifest.json')})
            for index, family in enumerate(FAMILIES):
                write(proof / 'frozen' / str(index) / 'seed.json', {'strategies': [{'request': {
                    'logicSummary': 'FitOnlyRisk' + family + '; frozen', 'sourceRef': 'local:' + str(index)}}]})
            write(inputs / 'READY.json', {'symbols': ['SYMBOL' + str(index) for index in range(10)]})
            queue = build_queue(proof, inputs)
            self.assertEqual(400, len(queue))
            self.assertEqual(400, len({row['strategy'] for row in queue}))
            self.assertEqual(50, len({(row['symbol'], row['scene']) for row in queue}))
            self.assertEqual(8, len({row['hypothesis'] for row in queue}))
            self.assertTrue(all('riskProfile' not in row for row in queue))
            self.assertEqual(8, sum(row['symbol'] == 'SYMBOL0' and row['scene'] == 'trend' for row in queue))
            self.assertEqual('catalog_ethusdt_range_b0b0117f812c',
                             strategy_name('ETHUSDT', 'range', 'fr1_trend_pullback_long_s15_t30'))

    def test_completed_observation_is_bound_to_source_scope_and_financial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = dict(strategy='frozen', symbol='BTCUSDT', scene='trend', hypothesis='x', family='FitOnlyRiskX')
            source = root / 'frozen/frozen/GeneratedStrategy.java'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'fixed')
            manifest = {'protocol_sha256': 'protocol', 'ready_sha256': 'ready',
                'fit_validation_oracle_manifest_sha256': 'proof', 'source_sha256': sha(source)}
            write(root / 'manifest.json', manifest)
            write(root / 'results.json', [dict(item, source_sha256=sha(source), qualified=False)])
            write(root / 'validation.json', {'pnl': -1})
            complete = {'manifest_sha256': sha(root / 'manifest.json'), 'results_sha256': sha(root / 'results.json'),
                'financial_outputs_sha256': {'validation.json': sha(root / 'validation.json')}}
            write(root / 'FORMAL_COMPLETE.json', complete)
            self.assertFalse(completed_observation(root, item, manifest, 'proof')['qualified'])
            write(root / 'validation.json', {'pnl': 1})
            with self.assertRaisesRegex(ValueError, 'metrics changed'):
                completed_observation(root, item, manifest, 'proof')


if __name__ == '__main__':
    unittest.main()
