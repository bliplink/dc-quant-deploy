import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recovery.export_true_adx_candidate import export_candidate, frozen_source, source_file, VARIANTS
from recovery.prepare_fixed_protocol_view import main as prepare_view
from recovery.run_true_adx_batch import frozen_queue, completed_case
from recovery.verify_fit_only_risk_contract import sha


NATIVE = '''package com.app.dc.service.strategy.research;
public class TrueAdxRepairStrategy extends LegacyLiveSignalAdapter {
    private static final String STRATEGY_NAME = "research_true_adx_directional_long";
    private static final String SYMBOL = "BTCUSDT";
    private static final int ENTRY_SIDE = 1;
    private static final boolean SELECTIVE = false;
    private static final int ADX_PERIOD = 14;
    private static final double ADX_THRESHOLD = 20.0;
    static double genuineDirectionalRecurrence() { return 14.0; }
}
'''


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class TrueAdxExportTest(unittest.TestCase):
    def test_four_exports_preserve_fixed_body_and_do_not_create_parameter_grid(self):
        names = set()
        for side, selective in VARIANTS:
            source, item, description = frozen_source(NATIVE, 'ETHUSDT', 'range', side, selective)
            names.add(item['strategyName'])
            self.assertIn('genuineDirectionalRecurrence() { return 14.0; }', source)
            self.assertIn('ADX_PERIOD = 14', source)
            self.assertIn('ADX_THRESHOLD = 20.0', source)
            self.assertIn('ENTRY_SIDE = ' + str(side), source)
            self.assertIn('SELECTIVE = ' + str(selective).lower(), source)
            self.assertIn('SYMBOL = "ETHUSDT"', source)
            self.assertEqual({}, item['request']['parameterSchema'])
            self.assertEqual({}, item['request']['defaultParameters'])
            self.assertEqual('wilder_adx_directional_breakout', description['mechanism_group'])
        self.assertEqual(4, len(names))

    def test_invalid_scope_or_mutated_native_contract_fail_closed(self):
        for symbol, scene, side, selective in [('BTC/USDT', 'trend', 1, False),
                ('BTCUSDT', 'unknown', 1, False), ('BTCUSDT', 'trend', True, False), ('BTCUSDT', 'trend', 1, 1)]:
            with self.assertRaises(ValueError):
                frozen_source(NATIVE, symbol, scene, side, selective)
        with self.assertRaisesRegex(ValueError, 'export contract changed'):
            frozen_source(NATIVE.replace('ADX_PERIOD = 14', 'ADX_PERIOD = 15').replace('ENTRY_SIDE = 1', 'ENTRY_SIDE = 2'),
                          'BTCUSDT', 'trend', 1, False)

    def test_export_cannot_overwrite_a_frozen_source_or_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = source_file(root / 'ind')
            native.parent.mkdir(parents=True)
            native.write_text(NATIVE, encoding='utf-8')
            frozen, item, _ = export_candidate(root / 'ind', root / 'frozen', 'BTCUSDT', 'trend', 1, False)
            export_candidate(root / 'ind', root / 'frozen', 'BTCUSDT', 'trend', 1, False)
            (frozen / 'GeneratedStrategy.java').write_text('modified', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                export_candidate(root / 'ind', root / 'frozen', 'BTCUSDT', 'trend', 1, False)

    def test_queue_is_two_hundred_scopes_but_only_one_conservative_mechanism_group(self):
        queue = frozen_queue(NATIVE, ['SYMBOL' + str(i) for i in range(10)])
        self.assertEqual(200, len(queue))
        self.assertEqual(200, len({r['strategy'] for r in queue}))
        self.assertEqual(50, len({(r['symbol'], r['scene']) for r in queue}))
        self.assertEqual(1, len({r['mechanism_group'] for r in queue}))

    def test_completed_financial_failure_is_bound_to_source_seed_artifact_and_raw_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, artifact = root / 'source.java', root / 'strategy.jar'
            source.write_bytes(b'frozen source')
            artifact.write_bytes(b'compiled artifact')
            write(root / 'seed.json', {'fixed': True})
            write(root / 'primary.json', {'primaryQualified': False, 'pnl': -1})
            contract = {'source_path': str(source), 'source_sha256': sha(source),
                'artifact_path': str(artifact), 'artifact_sha256': sha(artifact), 'seed_sha256': sha(root / 'seed.json')}
            write(root / 'source-contract.json', contract)
            record = {'qualified': False, 'source_sha256': sha(source)}
            write(root / 'checkpoint.json', {'manifest_sha256': 'fixed', 'record': record,
                'source_contract_sha256': sha(root / 'source-contract.json'),
                'financial_sha256': {'primary.json': sha(root / 'primary.json')}})
            self.assertFalse(completed_case(root, 'fixed')['qualified'])
            artifact.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'source/artifact/seed'):
                completed_case(root, 'fixed')
            artifact.write_bytes(b'compiled artifact')
            write(root / 'primary.json', {'primaryQualified': True, 'pnl': 1})
            with self.assertRaisesRegex(ValueError, 'financial output'):
                completed_case(root, 'fixed')

    def test_protocol_view_copies_exact_bytes_and_leaves_parent_metadata_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, output = root / 'parent', root / 'view'
            parent.mkdir()
            files = {}
            for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
                path = parent / ('BTCUSDT' + suffix)
                path.write_bytes(b'original exact bytes\n')
                files[key] = sha(path)
            ready = {'begin': '2024-12-15', 'primary_end_inclusive': '2025-10-12', 'holdout_begin': '2025-10-13',
                'end': '2025-12-13', 'symbols': ['BTCUSDT'], 'files': {'BTCUSDT': files}}
            write(parent / 'READY.json', ready)
            parent_hash = sha(parent / 'READY.json')
            protocol = dict(ready, protocol_version='temporal_source_research_v2', primary_begin=ready['begin'],
                holdout_end_inclusive=ready['end'], selection_mode='fixed_source_no_parameter_grid', source_cohort='true_adx_repair_v1')
            write(root / 'protocol.json', protocol)
            with patch('sys.argv', ['view', '--input-dir', str(parent), '--protocol', str(root / 'protocol.json'), '--output-dir', str(output)]):
                prepare_view()
            self.assertEqual(parent_hash, sha(parent / 'READY.json'))
            self.assertEqual(files['bars_sha256'], sha(output / 'BTCUSDT-15m.tsv'))
            self.assertEqual(files['scenes_sha256'], sha(output / 'BTCUSDT-scenes.tsv'))
            self.assertEqual(sha(root / 'protocol.json'), json.loads((output / 'READY.json').read_text())['protocol_sha256'])


if __name__ == '__main__':
    unittest.main()
