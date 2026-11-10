from argparse import Namespace
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from recovery import run_cusum_drift_batch as batch
from recovery import run_ohlcv_profile_proxy_batch as original
from recovery.test_cusum_drift import TEMPLATE
from recovery.verify_fit_only_risk_contract import sha

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT']


class CusumDriftBatchTest(unittest.TestCase):
    def fixture(self, root):
        rows = [dict(strategy='s' + str(i), symbol='BTCUSDT', scene='trend', hypothesis='dc1_overshoot_clock_long',
            family='CatalogAtrExitDirectionalClockHypothesis', side=1,
            mechanism_group='directional_change_overshoot_clock') for i in range(100)]
        (root / 'manifest.json').write_text(json.dumps(dict(schema=batch.PARENT_SCHEMA, queue=rows)))
        digest = sha(root / 'manifest.json')
        (root / 'FORMAL_COMPLETE.json').write_text(json.dumps(dict(manifest_sha256=digest, completed=100,
            local_formal_qualified=0, production_write=False)))
        (root / 'status.json').write_text(json.dumps(dict(completed=100, total=100, local_formal_qualified=0)))
        for row in rows:
            folder = root / 'candidates' / row['strategy']; folder.mkdir(parents=True)
            (folder / 'checkpoint.json').write_text('{}')
        parent = dict(pid=10, create_time=10.5, output_dir=str(root), manifest_sha256=digest)
        return rows, parent

    def test_entire_deterministic_hundred_scopes_are_one_mechanism(self):
        rows = batch.frozen_queue(TEMPLATE, SYMBOLS)
        self.assertEqual(rows, batch.frozen_queue(TEMPLATE, list(reversed(SYMBOLS))))
        self.assertEqual(100, len({r['strategy'] for r in rows}))
        self.assertEqual({'standardized_return_cusum_drift'}, {r['mechanism_group'] for r in rows})
        with self.assertRaises(ValueError): batch.frozen_queue(TEMPLATE, SYMBOLS[:-1])

    def test_only_exact_created_parent_command_and_plan_can_be_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.fixture(root)
            process = Mock(); process.create_time.return_value = 10.5
            process.cmdline.return_value = ['python', '-m', batch.PARENT_MODULE, '--output-dir', str(root)]
            with patch.object(batch.psutil, 'Process', return_value=process):
                bound = batch.bind_parent(10, 10.5, root, parent['manifest_sha256'])
                self.assertEqual(process.cmdline.return_value, bound['command'])
                with self.assertRaisesRegex(ValueError, 'reused'): batch.bind_parent(10, 99.5, root, parent['manifest_sha256'])
                process.cmdline.return_value = ['python', '-m', 'wrong', '--output-dir', str(root)]
                with self.assertRaisesRegex(ValueError, 'exact clock module'): batch.bind_parent(10, 10.5, root, parent['manifest_sha256'])
                with self.assertRaises(ValueError): batch.bind_parent(10, 10.5, root, 'different')

    def test_resume_preserves_original_parent_not_a_new_live_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.fixture(root)
            previous = dict(parent, command=['python', '-m', batch.PARENT_MODULE, '--output-dir', str(root)])
            with patch.object(batch.psutil, 'Process') as process:
                self.assertEqual(previous, batch.bind_parent(10, 10.5, root, parent['manifest_sha256'], previous))
                with self.assertRaisesRegex(ValueError, 'identity/plan changed'):
                    batch.bind_parent(11, 10.5, root, parent['manifest_sha256'], previous)
                process.assert_not_called()

    def test_parent_disappearance_is_not_completion_and_partial_or_failed_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.fixture(root)
            (root / 'FORMAL_COMPLETE.json').unlink()
            with self.assertRaises(FileNotFoundError): batch.require_parent_complete(parent)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.fixture(root)
            (root / 'status.json').write_text(json.dumps(dict(completed=99, total=100)))
            with self.assertRaises(ValueError): batch.require_parent_complete(parent)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.fixture(root); (root / 'FAILED.json').write_text('{}')
            with self.assertRaises(ValueError): batch.require_parent_complete(parent)

    def test_every_parent_source_artifact_and_financial_checkpoint_must_be_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); rows, parent = self.fixture(root)
            def saved(folder, digest):
                self.assertEqual(parent['manifest_sha256'], digest)
                return dict(rows[int(folder.name[1:])], qualified=False)
            with patch.object(batch, 'completed_case', side_effect=saved) as checked:
                audit = batch.require_parent_complete(parent)
            self.assertEqual(100, checked.call_count); self.assertEqual(100, len(audit['checkpoint_sha256']))
            self.assertFalse(audit['financial_replay_performed'])

    def test_parent_scope_mismatch_or_falsified_qualified_count_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); rows, parent = self.fixture(root)
            with patch.object(batch, 'completed_case', return_value=dict(rows[0], side=-1, qualified=False)):
                with self.assertRaisesRegex(ValueError, 'scope changed'): batch.require_parent_complete(parent)
            with patch.object(batch, 'completed_case', side_effect=lambda p, h: dict(rows[int(p.name[1:])], qualified=True)):
                with self.assertRaisesRegex(ValueError, 'qualification count'): batch.require_parent_complete(parent)

    def test_unchanged_original_financial_case_owns_strict_and_disjoint_holdout(self):
        self.assertIs(original.run_case, batch.run_case)
        self.assertEqual('recovery.run_ohlcv_profile_proxy_batch', batch.run_case.__module__)
        self.assertEqual(('strategy', 'symbol', 'scene', 'hypothesis', 'family', 'mechanism_group', 'side'), batch.SCOPE_FIELDS)

    def test_partial_financial_attempt_cannot_be_replayed_by_new_exporter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); row = batch.frozen_queue(TEMPLATE, SYMBOLS)[0]
            (root / 'candidates' / row['strategy']).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'partial attempt'):
                batch.run_case(Namespace(output_dir=root), row, 'frozen', {}, {}, '', '', {},
                    export_source=lambda *_: self.fail('must not export/replay'), scope_fields=batch.SCOPE_FIELDS)

    def test_original_case_receives_every_scope_and_same_export_hook_after_resources_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); engineering = root / 'engineering'; engineering.mkdir()
            (engineering / 'status.json').write_text(json.dumps({'records': []}))
            args = Namespace(output_dir=root, engineering_dir=engineering, reference_indsvr_repo=root, sim_repo=root)
            rows = batch.frozen_queue(TEMPLATE, SYMBOLS)
            proof = dict(source_sha256={}, classes_sha256={}, tool_sha256={})
            resources = Mock(side_effect=[{'ready': False}, {'ready': False}] + [{'ready': True}] * 101)
            with patch.object(batch, 'extra_slot_resources', resources), patch.object(batch, 'time', Namespace(sleep=Mock())) as clock, \
                 patch.object(batch, 'java_classpath', return_value='cp'), patch.object(batch, 'execute') as compile_helper, \
                 patch.object(batch, 'run_case', return_value=dict(qualified=False, reason='rejected')) as actual_case, \
                 redirect_stdout(io.StringIO()):
                batch.run_finance(args, dict(queue=rows, verification=proof), 'manifest', {}, {})
            self.assertEqual(100, actual_case.call_count); compile_helper.assert_called_once(); clock.sleep.assert_called_once_with(10)
            self.assertEqual(rows, [call.args[1] for call in actual_case.call_args_list])
            for call in actual_case.call_args_list:
                self.assertIs(batch.export_source, call.kwargs['export_source'])
                self.assertEqual(batch.SCOPE_FIELDS, call.kwargs['scope_fields'])
            self.assertEqual(100, json.loads((root / 'FORMAL_COMPLETE.json').read_text())['completed'])

    def test_changed_frozen_tool_after_resource_wait_prevents_even_helper_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tool = root / 'tool.py'; tool.write_text('original')
            proof = dict(source_sha256={}, classes_sha256={}, tool_sha256={str(tool): sha(tool)})
            tool.write_text('changed')
            with patch.object(batch, 'extra_slot_resources', return_value={'ready': True}), patch.object(batch, 'execute') as execute:
                with self.assertRaisesRegex(ValueError, 'changed'):
                    batch.run_finance(Namespace(output_dir=root), dict(verification=proof), 'hash', {}, {})
                execute.assert_not_called()


if __name__ == '__main__': unittest.main()
