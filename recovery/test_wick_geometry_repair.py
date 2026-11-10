import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from recovery.export_wick_geometry_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.run_wick_geometry_batch import frozen_queue, run_case
from recovery.verify_fit_only_risk_contract import sha


NATIVE = '''package com.app.dc.service.strategy.research;
public class WickGeometryRepairStrategy extends LegacyLiveSignalAdapter {
    private static final String STRATEGY_NAME = "research_wick_geometry_long";
    private static final String SYMBOL = "BTCUSDT";
    private static final int ENTRY_SIDE = 1;
    static double retainedActualRisk() { return 0.75; }
}
'''


class WickGeometryExportTest(unittest.TestCase):
    def test_two_directions_preserve_fixed_semantics_and_one_mechanism_group(self):
        names = set()
        for side in VARIANTS:
            source, item, description = frozen_source(NATIVE, 'ETHUSDT', 'range', side)
            names.add(item['strategyName'])
            self.assertIn('return 0.75;', source)
            self.assertIn('ENTRY_SIDE = ' + str(side), source)
            self.assertIn('SYMBOL = "ETHUSDT"', source)
            self.assertEqual({}, item['request']['parameterSchema'])
            self.assertEqual({}, item['request']['defaultParameters'])
            self.assertIn('risk0.75/1.5', item['request']['logicSummary'])
            self.assertEqual('wick_rejection_confirmation', description['mechanism_group'])
        self.assertEqual(2, len(names))

    def test_invalid_scope_boolean_direction_or_modified_template_fail_closed(self):
        for symbol, scene, side in [('BTC/USDT', 'trend', 1), ('BTCUSDT', 'unknown', 1), ('BTCUSDT', 'trend', True)]:
            with self.assertRaises(ValueError):
                frozen_source(NATIVE, symbol, scene, side)
        with self.assertRaisesRegex(ValueError, 'export contract changed'):
            frozen_source(NATIVE.replace('ENTRY_SIDE = 1', 'ENTRY_SIDE = 2'), 'BTCUSDT', 'trend', 1)

    def test_frozen_source_and_metadata_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = source_file(root / 'ind')
            native.parent.mkdir(parents=True)
            native.write_text(NATIVE, encoding='utf-8')
            folder, _, _ = export_candidate(root / 'ind', root / 'frozen', 'BTCUSDT', 'trend', 1)
            export_candidate(root / 'ind', root / 'frozen', 'BTCUSDT', 'trend', 1)
            seed = folder / 'seed.json'
            seed.write_text(json.dumps({'strategies': []}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'seed changed'):
                export_candidate(root / 'ind', root / 'frozen', 'BTCUSDT', 'trend', 1)

    def test_100_scopes_are_one_group_not_100_independent_mechanisms(self):
        rows = [frozen_source(NATIVE, 'SYMBOL' + str(index), scene, side)
                for index in range(10) for scene in ('trend', 'range', 'channel', 'breakout', 'reversal') for side in VARIANTS]
        self.assertEqual(100, len({row[1]['strategyName'] for row in rows}))
        self.assertEqual({'wick_rejection_confirmation'}, {row[2]['mechanism_group'] for row in rows})

    def test_runner_freezes_unique_scopes_and_rejects_duplicate_symbols(self):
        symbols = ['SYMBOL' + str(i) for i in range(10)]
        queue = frozen_queue(NATIVE, symbols)
        self.assertEqual(100, len(queue))
        self.assertEqual(50, len({(r['symbol'], r['scene']) for r in queue}))
        self.assertEqual({'wick_rejection_confirmation'}, {r['mechanism_group'] for r in queue})
        with self.assertRaises(ValueError):
            frozen_queue(NATIVE, symbols[:9] + [symbols[0]])

    def test_partial_attempt_is_never_silently_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'candidates/partial').mkdir(parents=True)
            with patch('recovery.run_wick_geometry_batch.export_candidate') as exporter:
                with self.assertRaisesRegex(ValueError, 'partial attempt'):
                    run_case(SimpleNamespace(output_dir=root), {'strategy': 'partial'}, 'hash', {}, {}, '', '', {})
                exporter.assert_not_called()

    def test_failed_primary_never_reads_holdout_and_completed_result_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = source_file(root / 'ind')
            native.parent.mkdir(parents=True)
            native.write_text(NATIVE, encoding='utf-8')
            output = root / 'batch'
            frozen, item, descriptor = export_candidate(root / 'ind', output / 'frozen', 'BTCUSDT', 'trend', 1)
            artifact = root / 'strategy.jar'
            artifact.write_bytes(b'compiled fixture')
            protocol = {'primary_begin': '2024-12-15', 'primary_end_inclusive': '2025-10-12',
                        'holdout_begin': '2025-10-13', 'holdout_end_inclusive': '2025-12-13'}
            protocol_path = root / 'protocol.json'
            protocol_path.write_text(json.dumps(protocol), encoding='utf-8')
            args = SimpleNamespace(output_dir=output, indsvr_repo=root / 'ind', protocol=protocol_path,
                                   input_dir=root / 'inputs', sim_repo=root / 'sim')
            row = dict(descriptor, strategy=item['strategyName'], symbol='BTCUSDT', scene='trend')
            original = {'source_sha256': sha(frozen / 'GeneratedStrategy.java'), 'artifact_sha256': sha(artifact),
                        'artifact_path': str(artifact), 'entry_class': 'fixture', 'signals': 12}
            ready = {'files': {'BTCUSDT': {'bars_sha256': 'bars', 'scenes_sha256': 'scenes'}}}

            def primary_only(command, log):
                self.assertTrue(any('FixedSourcePrimaryReplayCli' in arg for arg in command))
                target = Path(command[-1])
                result = {'primaryQualified': False, 'qualificationReason': 'oos_not_passed'}
                target.write_text(json.dumps(result), encoding='utf-8')
                target.with_name(target.name + '.engine.json').write_text(json.dumps(result), encoding='utf-8')

            with patch('recovery.run_wick_geometry_batch.execute', side_effect=primary_only) as execute:
                first = run_case(args, row, 'manifest', ready, protocol, '', '', {row['strategy']: original})
                self.assertFalse(first['qualified'])
                case = output / 'candidates' / row['strategy']
                self.assertFalse((case / 'HOLDOUT_STARTED.json').exists())
                second = run_case(args, row, 'manifest', ready, protocol, '', '', {})
                self.assertEqual(first, second)
                self.assertEqual(1, execute.call_count)
                with self.assertRaisesRegex(ValueError, 'mechanism changed'):
                    run_case(args, dict(row, mechanism_group='renamed'), 'manifest', ready, protocol, '', '', {})


if __name__ == '__main__':
    unittest.main()
