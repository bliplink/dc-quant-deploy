"""Synthetic resolver/control-flow tests; none are real-market financial qualifications."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from recovery import cusum_training_consumer as consumer
from recovery import cusum_training_proof_admission as admission
from recovery import run_ohlcv_profile_proxy_batch as batch
from recovery import test_cusum_training_proof_admission as admission_tests
from recovery.export_cusum_drift_candidate import export_candidate, source_file
from recovery.run_cusum_drift_batch import SCOPE_FIELDS, frozen_queue
from recovery.test_cusum_drift import TEMPLATE
from recovery.test_cusum_identity_matrix import SYMBOLS
from recovery.verify_cusum_identity_matrix import digest_json
from recovery.verify_fit_only_risk_contract import sha


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class TrainingResolverTest(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.CusumTrainingAdmissionTest()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.rows, self.canonical, self.records = self.fixture.group_fixture()
        queue = frozen_queue(TEMPLATE, SYMBOLS)
        self.manifest = dict(queue=queue, context={'test_fixture_only': True})
        self.matrix = dict(scope_records=self.records, canonical_references=[self.canonical])
        self.resolver = consumer.VerifiedCusumTrainingResolver.__new__(consumer.VerifiedCusumTrainingResolver)
        self.resolver.root = self.fixture.root; self.resolver.matrix_sha256 = 'f' * 64
        self.resolver.environment_args = object()
        self.addCleanup(patch.stopall)
        self.terminal = patch.object(admission, 'terminal_documents', return_value=(self.manifest, self.matrix)).start()
        self.environment = patch.object(admission, 'require_environment').start()

    def resolve(self, row=None):
        record = self.records[0]
        return self.resolver(row or self.rows[0], Path(record['source_path']), Path(record['seed_path']))

    def test_constructor_requires_real_complete_matrix_before_providing_any_resolver(self):
        with patch.object(admission, 'verify_complete_matrix', side_effect=ValueError('incomplete matrix')) as verify:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                consumer.VerifiedCusumTrainingResolver(self.fixture.root, 'f' * 64, object())
            verify.assert_called_once()

    def test_exact_own_source_seed_and_full_three_class_group_produce_bound_receipt(self):
        proof = self.resolve()
        self.assertEqual(2, self.terminal.call_count); self.assertEqual(2, self.environment.call_count)
        self.assertEqual(10, proof['signals'])
        receipt = consumer.require_receipt(proof, self.rows[0], self.records[0]['source_path'],
            self.records[0]['seed_path'], proof['artifact_path'], proof['signals'])
        self.assertIs(False, receipt['financial_replay_performed']); self.assertIs(False, receipt['production_write'])
        self.assertEqual(sha(self.fixture.root / 'groups' / 'ADAUSDT' / 'long' / 'GROUP_COMPLETE.json'), receipt['group_marker_sha256'])

    def test_changed_current_source_scene_or_artifact_cannot_return_a_proof(self):
        for change in (dict(symbol='OTHERUSDT'), dict(scene='range'), dict(side=-1)):
            with self.assertRaises(ValueError): self.resolve(dict(self.rows[0], **change))
        Path(self.records[0]['source_path']).write_text('changed source')
        with self.assertRaises(ValueError): self.resolve()

    def test_missing_scope_or_environment_change_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, 'scope absent'): self.resolve(dict(self.rows[0], strategy='unknown'))
        self.environment.side_effect = ValueError('classpath changed')
        with self.assertRaisesRegex(ValueError, 'classpath'): self.resolve()

    def test_a_change_at_the_final_terminal_boundary_prevents_returning_a_receipt(self):
        self.terminal.side_effect = [(self.manifest, self.matrix), ValueError('terminal matrix changed')]
        with self.assertRaisesRegex(ValueError, 'terminal matrix changed'): self.resolve()

    def test_receipt_digest_and_consumer_bytes_are_checked_again(self):
        proof = self.resolve(); source, seed = self.records[0]['source_path'], self.records[0]['seed_path']
        changed = copy.deepcopy(proof); changed['training_proof_receipt']['scene'] = 'range'
        with self.assertRaises(ValueError): consumer.require_receipt(changed, self.rows[0], source, seed, proof['artifact_path'], 10)
        changed['training_proof_receipt_sha256'] = digest_json(changed['training_proof_receipt'])
        with self.assertRaises(ValueError): consumer.require_receipt(changed, self.rows[0], source, seed, proof['artifact_path'], 10)
        Path(seed).write_text('{}')
        with self.assertRaises(ValueError): consumer.require_receipt(proof, self.rows[0], source, seed, proof['artifact_path'], 10)


class RunCaseTrainingHookTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = SimpleNamespace(output_dir=self.root / 'output', indsvr_repo=self.root / 'ind',
            sim_repo=self.root / 'sim', training_input_dir=self.root / 'training', input_dir=self.root / 'market',
            protocol=self.root / 'protocol.json')
        native = source_file(self.args.indsvr_repo); native.parent.mkdir(parents=True); native.write_text(TEMPLATE)
        self.args.output_dir.mkdir(); save(self.args.protocol, {'unit_fixture': True})
        self.row = frozen_queue(TEMPLATE, SYMBOLS)[0]
        self.ready = {'files': {self.row['symbol']: dict(bars_sha256='bars', scenes_sha256='scenes')}}
        self.protocol = dict(primary_begin='2024-12-15', primary_end_inclusive='2025-10-12',
            holdout_begin='2025-10-13', holdout_end_inclusive='2025-12-13')
        self.artifact = self.root / 'artifact.jar'; self.artifact.write_bytes(b'unit fixture, not compiled Java')
        self.primary = dict(primaryQualified=False, qualificationReason='oos_not_passed',
            result={'unit_fixture': True}, selectedParameters={}, parameterGridSearch=False)
        self.holdout = dict(passed=False, unit_fixture=True)
        self.commands = []
        self.addCleanup(patch.stopall)
        self.execute = patch.object(batch, 'execute', side_effect=self.fake_execute).start()
        self.compile = patch.object(batch, 'compile_source', return_value=(self.artifact, 'fixture.Entry', None)).start()
        self.strict = patch.object(batch, 'strict_primary', return_value=(False, {'qualified': False, 'reason': 'strict_rejection'})).start()
        self.temporal = patch.object(batch, 'require_temporally_isolated_admission').start()
        self.resolver = Mock(side_effect=self.proof)

    def export(self, args, row):
        return export_candidate(args.indsvr_repo, args.output_dir / 'frozen', row['symbol'], row['scene'], row['side'])

    def proof(self, row, source, seed):
        receipt = dict(schema='verified_cusum_training_consumption_v1', matrix_manifest_sha256=admission.MANIFEST_SHA256,
            context_sha256=admission.CONTEXT_SHA256, strategy=row['strategy'], symbol=row['symbol'], scene=row['scene'], side=row['side'],
            matrix_sha256='f' * 64, group_marker_sha256='f' * 64, scope_proof_sha256='f' * 64,
            actual_canonical_full_year_log_sha256='f' * 64,
            training_evidence_mode='actual_canonical_full_year_and_exact_source_full_class_identity',
            current_source_sha256=sha(source), current_seed_sha256=sha(seed), artifact_sha256=sha(self.artifact),
            training_bars=35040, training_signals=10, mismatches=0, training_check_reuse_verified=True,
            financial_replay_performed=False, production_write=False)
        return dict(source_sha256=sha(source), artifact_path=str(self.artifact), artifact_sha256=sha(self.artifact),
            entry_class='fixture.Entry', signals=10, training_proof_receipt=receipt, training_proof_receipt_sha256=digest_json(receipt))

    def fake_execute(self, command, log):
        self.commands.append(command)
        for label, result in (('primary', self.primary), ('holdout', self.holdout)):
            if str(log).endswith(label + '.log'):
                save(Path(log).with_suffix('.json'), result)
                save(Path(log).with_suffix('.json.engine.json'), {'unit_fixture': True})
        return 'bars=35040, researchSignals=10, exportedSignals=10, mismatches=0'

    def run_case(self, cached=True):
        return batch.run_case(self.args, self.row, 'manifest', self.ready, self.protocol, 'finance-cp', 'parity-cp', {},
            export_source=self.export, scope_fields=SCOPE_FIELDS,
            **({'training_proof_resolver': self.resolver} if cached else {}))

    def test_original_financial_tail_is_byte_identical_after_lf_normalization(self):
        source = Path(batch.__file__).read_text(encoding='utf-8')
        begin = source.index("    files = ready['files'][row['symbol']]")
        end = source.index('\ndef main():', begin)
        self.assertEqual('7feaa47b44aed5f1db03e772671098282279ac602832b96264176ac413171609',
            hashlib.sha256(source[begin:end].encode()).hexdigest())

    def test_cached_training_still_runs_original_primary_and_strict_gate(self):
        record = self.run_case(); self.assertIs(False, record['qualified'])
        self.compile.assert_not_called(); self.strict.assert_called_once()
        self.assertEqual(1, len(self.commands)); self.assertIn('FixedSourcePrimaryReplayCli', ' '.join(self.commands[0]))
        contract = json.loads((self.args.output_dir / 'candidates' / self.row['strategy'] / 'source-contract.json').read_text())
        self.assertEqual(sha(self.artifact), contract['artifact_sha256'])
        self.assertEqual(digest_json(contract['training_proof_receipt']), contract['training_proof_receipt_sha256'])

    def test_raw_primary_pass_but_strict_rejection_does_not_run_holdout(self):
        self.primary['primaryQualified'] = True
        record = self.run_case(); self.assertIs(False, record['qualified']); self.temporal.assert_not_called()
        self.assertEqual('strict_rejection', record['reason']); self.assertEqual(1, len(self.commands))

    def test_strict_primary_pass_still_executes_unchanged_disjoint_holdout(self):
        self.primary['primaryQualified'] = True; self.strict.return_value = (True, {'qualified': True, 'reason': 'qualified'})
        record = self.run_case(); self.assertIs(False, record['qualified']); self.assertEqual(2, len(self.commands))
        self.assertIn('OfflineTemporalReplayCli', ' '.join(self.commands[1])); self.temporal.assert_called_once()
        spec = json.loads((self.args.output_dir / 'candidates' / self.row['strategy'] / 'holdout-spec.json').read_text())
        self.assertEqual('2025-10-13', spec['beginDate']); self.assertEqual('2025-12-13', spec['endDate'])
        self.assertEqual('2025-10-12', spec['primaryEndDate']); self.assertIs(True, spec['formalHoldout'])
        self.assertEqual({}, spec['lockedParameters'])

    def test_empty_proof_or_bad_receipt_stops_before_financial_dispatch_without_fallback(self):
        self.resolver.side_effect = None; self.resolver.return_value = None
        with self.assertRaisesRegex(ValueError, 'complete training proof'): self.run_case()
        self.compile.assert_not_called(); self.execute.assert_not_called(); self.strict.assert_not_called()
        case = self.args.output_dir / 'candidates' / self.row['strategy']
        self.assertFalse((case / 'PRIMARY_STARTED.json').exists())

    def test_changed_receipt_is_rejected_before_primary(self):
        def invalid(row, source, seed):
            proof = self.proof(row, source, seed); proof['training_proof_receipt']['current_seed_sha256'] = 'changed'
            proof['training_proof_receipt_sha256'] = digest_json(proof['training_proof_receipt']); return proof
        self.resolver.side_effect = invalid
        with self.assertRaisesRegex(ValueError, 'receipt changed'): self.run_case()
        self.compile.assert_not_called(); self.execute.assert_not_called()

    def test_legacy_no_resolver_path_keeps_original_compile_validator_parity_and_finance(self):
        record = self.run_case(cached=False)
        self.assertIs(False, record['qualified']); self.compile.assert_called_once(); self.resolver.assert_not_called()
        self.assertEqual(3, len(self.commands)); self.assertIn('--validate-source', self.commands[0])
        self.assertIn('2023-01-01', self.commands[1]); self.assertIn('2023-12-31', self.commands[1])
        self.assertIn('FixedSourcePrimaryReplayCli', ' '.join(self.commands[2]))

    def test_existing_completed_or_partial_cases_are_not_replayed_to_enable_training_reuse(self):
        case = self.args.output_dir / 'candidates' / self.row['strategy']; case.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'partial attempt'): self.run_case()
        save(case / 'checkpoint.json', {})
        with patch.object(batch, 'completed_case', return_value=self.row):
            self.assertEqual(self.row, self.run_case())
        self.resolver.assert_not_called(); self.compile.assert_not_called(); self.execute.assert_not_called()


if __name__ == '__main__': unittest.main()
