"""Orchestration and fail-closed controls; mock finance outputs are not market qualifications."""
from argparse import Namespace
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from recovery import run_ehlers_fisher_batch as batch
from recovery import run_ohlcv_profile_proxy_batch as original
from recovery.test_ehlers_fisher import TEMPLATE
from recovery.test_cusum_identity_matrix import SYMBOLS
from recovery.verify_fit_only_risk_contract import sha


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value), encoding='utf-8')


class EhlersFisherBatchTest(unittest.TestCase):
    def setUp(self):
        fixture_process = patch.object(batch.psutil, 'pid_exists', return_value=False)
        fixture_process.start(); self.addCleanup(fixture_process.stop)

    def test_complete_marker_cannot_release_an_exact_still_living_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); _,parent=self.parent_fixture(root)
            with patch.object(batch.psutil,'pid_exists',return_value=True), patch.object(batch.psutil,'Process') as process, patch.object(batch,'completed_case') as checked:
                process.return_value.create_time.return_value=parent['create_time']
                process.return_value.cmdline.return_value=['changed']
                with self.assertRaisesRegex(ValueError,'exit naturally'):batch.require_parent_complete(parent)
                checked.assert_not_called()

    def test_entire_financial_executor_body_is_unchanged_except_log_label(self):
        import inspect
        from recovery import run_runs_clustering_batch as old
        self.assertEqual(inspect.getsource(old.run_finance),
            inspect.getsource(batch.run_finance).replace('EHLERS_FISHER_FORMAL','RUNS_CLUSTERING_FORMAL'))

    def parent_fixture(self, root):
        rows = [dict(strategy='s' + str(i), symbol='BTCUSDT', scene='trend', hypothesis='cs1_standardized_drift_long',
            family='CatalogAtrExitCusumDriftHypothesis', side=1, mechanism_group='standardized_return_cusum_drift') for i in range(100)]
        save(root / 'manifest.json', dict(schema=batch.PARENT_SCHEMA, queue=rows))
        digest = sha(root / 'manifest.json')
        save(root / 'FORMAL_COMPLETE.json', dict(manifest_sha256=digest, completed=100, local_formal_qualified=0, production_write=False))
        save(root / 'status.json', dict(completed=100, total=100, local_formal_qualified=0))
        for row in rows: save(root / 'candidates' / row['strategy'] / 'checkpoint.json', {})
        return rows, dict(pid=10, create_time=10.5, output_dir=str(root), manifest_sha256=digest)

    def test_entire_hundred_deterministic_scopes_are_one_conservative_group(self):
        rows = batch.frozen_queue(TEMPLATE, SYMBOLS)
        self.assertEqual(rows, batch.frozen_queue(TEMPLATE, list(reversed(SYMBOLS))))
        self.assertEqual(100, len({r['strategy'] for r in rows}))
        self.assertEqual({'ehlers_recursive_fisher_reversal'}, {r['mechanism_group'] for r in rows})
        with self.assertRaises(ValueError): batch.frozen_queue(TEMPLATE, SYMBOLS[:-1])

    def test_only_exact_parent_create_module_output_and_manifest_are_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.parent_fixture(root)
            process = Mock(); process.create_time.return_value = 10.5
            process.cmdline.return_value = ['python', '-m', batch.PARENT_MODULE, '--output-dir', str(root)]
            with patch.object(batch.psutil, 'Process', return_value=process):
                saved = batch.bind_parent(10, 10.5, root, parent['manifest_sha256'])
                self.assertEqual(process.cmdline.return_value, saved['command'])
                with self.assertRaisesRegex(ValueError, 'reused'): batch.bind_parent(10, 11, root, parent['manifest_sha256'])
                process.cmdline.return_value = ['python', '-m', 'wrong', '--output-dir', str(root)]
                with self.assertRaisesRegex(ValueError, 'exact CUSUM'): batch.bind_parent(10, 10.5, root, parent['manifest_sha256'])
                with self.assertRaises(ValueError): batch.bind_parent(10, 10.5, root, 'different')

    def test_recorded_live_identity_can_survive_parent_exit_without_selecting_a_new_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.parent_fixture(root)
            saved = dict(parent, command=['python', '-m', batch.PARENT_MODULE, '--output-dir', str(root)])
            with patch.object(batch.psutil, 'Process') as process:
                self.assertEqual(saved, batch.bind_parent(10, 10.5, root, parent['manifest_sha256'], saved))
                with self.assertRaisesRegex(ValueError, 'identity/plan changed'):
                    batch.bind_parent(11, 10.5, root, parent['manifest_sha256'], saved)
                process.assert_not_called()

    def test_parent_disappearance_missing_marker_partial_status_or_failure_is_not_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.parent_fixture(root)
            (root / 'FORMAL_COMPLETE.json').unlink()
            with self.assertRaises(FileNotFoundError): batch.require_parent_complete(parent)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.parent_fixture(root)
            save(root / 'status.json', dict(completed=99, total=100))
            with self.assertRaises(ValueError): batch.require_parent_complete(parent)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); _, parent = self.parent_fixture(root); save(root / 'FAILED.json', {})
            with self.assertRaises(ValueError): batch.require_parent_complete(parent)

    def test_all_hundred_actual_checkpoint_verifiers_are_called_without_financial_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); rows, parent = self.parent_fixture(root)
            def saved(folder, digest):
                self.assertEqual(parent['manifest_sha256'], digest); return dict(rows[int(folder.name[1:])], qualified=False)
            with patch.object(batch, 'completed_case', side_effect=saved) as checked:
                audit = batch.require_parent_complete(parent)
            self.assertEqual(100, checked.call_count); self.assertEqual(100, len(audit['checkpoint_sha256']))
            self.assertIs(False, audit['financial_replay_performed'])

    def test_scope_mismatch_and_falsified_parent_qualification_count_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); rows, parent = self.parent_fixture(root)
            with patch.object(batch, 'completed_case', return_value=dict(rows[0], side=-1, qualified=False)):
                with self.assertRaisesRegex(ValueError, 'scope changed'): batch.require_parent_complete(parent)
            with patch.object(batch, 'completed_case', side_effect=lambda p,h: dict(rows[int(p.name[1:])], qualified=True)):
                with self.assertRaisesRegex(ValueError, 'qualification count'): batch.require_parent_complete(parent)

    def test_incomplete_engineering_prevents_even_formal_helper_proof_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(engineering_dir=Path(temporary))
            with patch.object(batch, 'require_proof') as proof, patch.object(batch, 'execute') as execute:
                with self.assertRaisesRegex(ValueError, 'complete successful'): batch.verify_context(args)
                proof.assert_not_called(); execute.assert_not_called()
            save(args.engineering_dir / 'FAILED.json', {})
            with self.assertRaisesRegex(ValueError, 'complete successful'): batch.engineering_evidence(args)

    def test_engineering_headers_cannot_replace_missing_mathematics_or_regression_proofs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); save(root / 'manifest.json', dict(schema='ehlers_fisher_engineering_v1',
                mechanism_group='ehlers_recursive_fisher_reversal', financial_validation_started=False,
                forward_pnl_read=False, production_write=False))
            marker = dict(manifest_sha256=sha(root / 'manifest.json'), completed=2, mathematics_tests=15,
                independent_raw_ohlc_fixtures=64, independent_expanded_convolution_oracle=True, regression_tests=187,
                financial_validation_started=False, production_write=False)
            save(root / 'status.json', dict(state='COMPLETE', completed=2, total=2))
            for changed in (dict(completed=1), dict(mathematics_tests=14), dict(independent_raw_ohlc_fixtures=63),
                    dict(independent_expanded_convolution_oracle=False), dict(regression_tests=186),
                    dict(financial_validation_started=True), dict(production_write=True)):
                save(root / 'SOURCE_CONTRACT_COMPLETE.json', dict(marker, **changed))
                with self.assertRaisesRegex(ValueError, 'genuine15/64'):
                    batch.engineering_evidence(Namespace(engineering_dir=root, engineering_manifest_sha256=marker['manifest_sha256']))

    def test_original_financial_case_is_reused_not_reimplemented(self):
        self.assertIs(original.run_case, batch.run_case)
        self.assertEqual('recovery.run_ohlcv_profile_proxy_batch', batch.run_case.__module__)
        self.assertEqual(('strategy', 'symbol', 'scene', 'hypothesis', 'family', 'mechanism_group', 'side'), batch.SCOPE_FIELDS)

    def test_partial_financial_attempt_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); row = batch.frozen_queue(TEMPLATE, SYMBOLS)[0]
            (root / 'candidates' / row['strategy']).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'partial attempt'):
                batch.run_case(Namespace(output_dir=root), row, 'hash', {}, {}, '', '', {},
                    export_source=lambda *_: self.fail('no replay'), scope_fields=batch.SCOPE_FIELDS)

    def test_all_original_financial_scopes_receive_the_fixed_exporter_after_resource_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); args = Namespace(output_dir=root, engineering_dir=root, reference_indsvr_repo=root, sim_repo=root)
            rows = batch.frozen_queue(TEMPLATE, SYMBOLS); proof = dict(original_records=[])
            with patch.object(batch, 'extra_slot_resources', side_effect=[{'ready':False}, {'ready':True}]+[{'ready':True}]*100), \
                    patch.object(batch, 'time', Namespace(sleep=Mock())) as clock, patch.object(batch, 'check_snapshot') as checked, \
                    patch.object(batch, 'java_classpath', return_value='cp'), patch.object(batch, 'execute') as compiler, \
                    patch.object(batch, 'run_case', return_value=dict(qualified=False,reason='rejected')) as actual, redirect_stdout(io.StringIO()):
                batch.run_finance(args,dict(queue=rows,verification=proof),'hash',{}, {})
            self.assertEqual(100, actual.call_count); self.assertEqual(101, checked.call_count)
            compiler.assert_called_once(); clock.sleep.assert_called_once_with(10)
            self.assertEqual(rows,[call.args[1] for call in actual.call_args_list])
            for call in actual.call_args_list:
                self.assertIs(batch.export_source,call.kwargs['export_source']); self.assertNotIn('training_proof_resolver',call.kwargs)
            self.assertEqual(100,json.loads((root/'FORMAL_COMPLETE.json').read_text())['completed'])

    def test_changed_snapshot_prevents_even_helper_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = Namespace(output_dir=Path(temporary))
            with patch.object(batch,'extra_slot_resources',return_value={'ready':True}), \
                    patch.object(batch,'check_snapshot',side_effect=ValueError('changed frozen context')), patch.object(batch,'execute') as execute:
                with self.assertRaisesRegex(ValueError,'changed frozen'): batch.run_finance(args,dict(verification={}), 'hash',{}, {})
                execute.assert_not_called()

    def test_runtime_class_jar_membership_and_scoped_data_cannot_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); classes=root/'classes'; classes.mkdir(); jars=root/'jars'; jars.mkdir()
            bytecode=classes/'One.class'; bytecode.write_bytes(b'original'); jar=jars/'one.jar'; jar.write_bytes(b'original')
            java=root/'java.exe'; java.write_bytes(b'original'); data=root/'BTCUSDT-15m.tsv'; data.write_bytes(b'original')
            proof=dict(source_sha256={},classes_sha256={str(bytecode):sha(bytecode)},tool_sha256={str(java):sha(java)},
                runtime_jar_sha256={str(jar):sha(jar)},runtime_jar_roots=[str(jars)],runtime_class_sha256={str(bytecode):sha(bytecode)},
                runtime_class_roots=[str(classes)],java_executables={'java':str(java)},java_option_environment_sha256={},
                data_sha256={str(data):sha(data)})
            with patch.object(batch.shutil,'which',return_value=str(java)):
                batch.check_snapshot(proof)
                (classes/'Extra.class').write_bytes(b'extra')
                with self.assertRaisesRegex(ValueError,'runtime membership'): batch.check_snapshot(proof)
                (classes/'Extra.class').unlink(); (jars/'extra.jar').write_bytes(b'extra')
                with self.assertRaisesRegex(ValueError,'runtime membership'): batch.check_snapshot(proof)
                (jars/'extra.jar').unlink()
                empty=root/'initially-empty-jars'; empty.mkdir(); proof['runtime_jar_roots'].append(str(empty))
                batch.check_snapshot(proof); (empty/'extra.jar').write_bytes(b'extra')
                with self.assertRaisesRegex(ValueError,'runtime membership'): batch.check_snapshot(proof)
                (empty/'extra.jar').unlink(); data.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'changed'): batch.check_snapshot(proof,dict(symbol='BTCUSDT'))


if __name__ == '__main__': unittest.main()
