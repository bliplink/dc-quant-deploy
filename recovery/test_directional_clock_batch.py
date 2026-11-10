from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recovery.clone_temporal_protocol_view import clone_view
from recovery.run_directional_clock_batch import frozen_queue, require_hashes, require_parent_complete, SCOPE_FIELDS
from recovery.run_ohlcv_profile_proxy_batch import run_case
from recovery import test_directional_clock as export_fixtures
from recovery.verify_fit_only_risk_contract import sha


class DirectionalClockBatchTest(unittest.TestCase):
    def row(self):
        return dict(strategy='fixed', hypothesis='dc1_overshoot_clock_long', family='CatalogAtrExitDirectionalClockHypothesis',
                    mechanism_group='directional_change_overshoot_clock', symbol='BTCUSDT', scene='trend', side=1)

    def test_queue_is_one_hundred_scopes_but_one_conservative_group(self):
        symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT']
        rows = frozen_queue(export_fixtures.DirectionalClockSourceTest().template(), symbols)
        self.assertEqual(rows, frozen_queue(export_fixtures.DirectionalClockSourceTest().template(), list(reversed(symbols))))
        self.assertEqual(100, len({row['strategy'] for row in rows}))
        self.assertEqual({'directional_change_overshoot_clock'}, {row['mechanism_group'] for row in rows})
        with self.assertRaises(ValueError): frozen_queue(export_fixtures.DirectionalClockSourceTest().template(), symbols[:-1])

    def test_checkpoint_preserves_completed_failure_without_mode_or_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); folder = root / 'candidates/fixed'; folder.mkdir(parents=True)
            (folder / 'checkpoint.json').write_text('{}'); row = self.row(); record = dict(row, qualified=False)
            with patch('recovery.run_ohlcv_profile_proxy_batch.completed_case', return_value=record), \
                 patch('recovery.run_ohlcv_profile_proxy_batch.execute') as execute:
                self.assertEqual(record, run_case(Namespace(output_dir=root), row, 'h', {}, {}, '', '', {}, scope_fields=SCOPE_FIELDS))
                with self.assertRaises(ValueError):
                    run_case(Namespace(output_dir=root), dict(row, mechanism_group='renamed'), 'h', {}, {}, '', '', {}, scope_fields=SCOPE_FIELDS)
                execute.assert_not_called()

    def test_new_source_hook_cannot_send_a_strict_contribution_failure_to_holdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); frozen = root / 'frozen/fixed'; frozen.mkdir(parents=True)
            source = frozen / 'GeneratedStrategy.java'; source.write_text('source')
            (frozen / 'seed.json').write_text('{}'); artifact = root / 'source.jar'; artifact.write_bytes(b'jar')
            protocol = root / 'protocol.json'; protocol.write_text('{}')
            primary = dict(primaryQualified=True, qualificationReason='qualified', selectedParameters={}, parameterGridSearch=False,
                result=dict(executionModelVersion='v4_non_overlapping_walk_forward', oosPass=1, tradeCount=30,
                    profitFactor=1.5, maxDrawdownPct=.05, feeAdjustedValidatePnl=50, feeAdjustedForwardPnl=19.9,
                    totalPnl=100, minForwardContribution=0))
            item = {'request': {'parameterSchema': {}, 'defaultParameters': {}, 'optimizationProfile': {'minForwardContribution': .2}}}
            proof = {'fixed': dict(source_sha256=sha(source), artifact_sha256=sha(artifact), artifact_path=str(artifact), entry_class='test.Entry', signals=1)}
            args = Namespace(output_dir=root, protocol=protocol, input_dir=root, sim_repo=root)
            ready = {'files': {'BTCUSDT': {'bars_sha256': 'bars', 'scenes_sha256': 'scenes'}}}
            dates = dict(primary_begin='2024-12-15', primary_end_inclusive='2025-10-12', holdout_begin='2025-10-13', holdout_end_inclusive='2025-12-13')
            commands = []

            def fake_execute(command, log):
                commands.append(command); Path(command[-1]).write_text(json.dumps(primary)); return ''

            with patch('recovery.run_ohlcv_profile_proxy_batch.execute', side_effect=fake_execute):
                result = run_case(args, self.row(), 'manifest', ready, dates, 'cp', 'cp', proof,
                    export_source=lambda args, row: (frozen, item, row), scope_fields=SCOPE_FIELDS)
            self.assertFalse(result['qualified']); self.assertEqual(1, len(commands))
            self.assertIn('com.app.dc.service.simulation.FixedSourcePrimaryReplayCli', commands[0])
            self.assertFalse((root / 'candidates/fixed/HOLDOUT_STARTED.json').exists())

    def test_partial_attempt_is_not_replayed_through_source_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'candidates/fixed').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'partial attempt'):
                run_case(Namespace(output_dir=root), self.row(), 'hash', {}, {}, '', '', {},
                         export_source=lambda *_: self.fail('must not export'), scope_fields=SCOPE_FIELDS)

    def test_exact_parent_financial_checkpoints_required_not_just_pid_disappearance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); rows = [dict(self.row(), strategy='s' + str(i)) for i in range(200)]
            (root / 'manifest.json').write_text(json.dumps({'queue': rows}))
            parent = {'output_dir': str(root), 'manifest_sha256': sha(root / 'manifest.json')}
            with self.assertRaises(FileNotFoundError): require_parent_complete(parent)
            (root / 'FORMAL_COMPLETE.json').write_text(json.dumps(dict(manifest_sha256=parent['manifest_sha256'], completed=200, production_write=False)))
            (root / 'status.json').write_text(json.dumps(dict(completed=200, total=200)))
            with patch('recovery.run_directional_clock_batch.completed_case', side_effect=lambda folder, h: rows[int(folder.name[1:])]) as checked:
                require_parent_complete(parent); self.assertEqual(200, checked.call_count)
            (root / 'status.json').write_text(json.dumps(dict(completed=199, total=200)))
            with self.assertRaises(ValueError): require_parent_complete(parent)

    def test_changed_tool_after_wait_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary) / 'tool.py'; p.write_text('original'); expected = {str(p): sha(p)}
            require_hashes(expected); p.write_text('changed')
            with self.assertRaises(ValueError): require_hashes(expected)

    def test_protocol_view_preserves_market_bytes_and_refuses_changed_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; source.mkdir()
            bars, scenes = source / 'BTCUSDT-15m.tsv', source / 'BTCUSDT-scenes.tsv'
            bars.write_bytes(b'original-market\n'); scenes.write_bytes(b'original-scenes\n')
            p = json.loads(Path(__file__).with_name('strategy_research_directional_clock_protocol_20261111.json').read_text())
            protocol = root / 'protocol.json'; protocol.write_text(json.dumps(p))
            ready = dict(protocol_version='temporal_source_research_v2', clock='UTC', production_write=False,
                begin=p['primary_begin'], primary_end_inclusive=p['primary_end_inclusive'], holdout_begin=p['holdout_begin'],
                end=p['holdout_end_inclusive'], minimum_holdout_calendar_days=62, symbols=['BTCUSDT'],
                files={'BTCUSDT': {'bars_sha256': sha(bars), 'scenes_sha256': sha(scenes)}})
            (source / 'READY.json').write_text(json.dumps(ready)); copy = root / 'copy'
            result = clone_view(source, copy, protocol)
            self.assertEqual(bars.read_bytes(), (copy / bars.name).read_bytes())
            self.assertEqual(sha(protocol), result['protocol_sha256'])
            with self.assertRaises(ValueError): clone_view(source, copy, protocol)
            bars.write_bytes(b'changed')
            with self.assertRaises(ValueError): clone_view(source, root / 'other', protocol)


if __name__ == '__main__': unittest.main()
