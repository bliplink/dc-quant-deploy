"""Synthetic admission controls, not strategy profitability or real JVM coverage."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from recovery import cusum_training_proof_admission as gate
from recovery.class_identity_equivalence import identity_prefix, require_jar_identity_equivalence
from recovery.test_class_identity_equivalence import fixture_class, fixture_source
from recovery import test_cusum_identity_matrix as matrix_tests


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')


class CusumTrainingAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def terminal_fixture(self):
        queue, canonicals, records = matrix_tests.CusumIdentityMatrixTest().records()
        context = {'synthetic_unit_fixture': True}
        context_sha = gate.digest_json(context)
        for record in records: record['context_sha256'] = context_sha
        self.manifest = dict(schema='cusum_complete_training_identity_matrix_v1', queue=queue, context=context,
            canonical_groups=20, scope_proofs=100, mechanism_groups=1,
            runtime_reuse_enabled=False, financial_validation_started=False, new_holdout_read=False, production_write=False)
        save(self.root / 'manifest.json', self.manifest)
        manifest_sha = gate.sha(self.root / 'manifest.json')
        self.matrix = dict(manifest_sha256=manifest_sha, context_sha256=context_sha, canonical_references=canonicals,
            scope_records=records, actual_full_year_replays=20, actual_source_validations=100, actual_scope_compilations=100,
            runtime_reuse_enabled=False, runtime_admission_ready=False, financial_validation_started=False,
            new_holdout_read=False, production_write=False)
        self.marker = dict(manifest_sha256=manifest_sha, completed_groups=20, completed_scopes=100,
            nonzero_reference_groups=20, runtime_reuse_enabled=False, runtime_admission_ready=False, production_write=False)
        self.status = dict(state='COMPLETE', completed_groups=20, total_groups=20, completed_scopes=100, total_scopes=100,
            runtime_reuse_enabled=False, financial_validation_started=False, production_write=False)
        self.addCleanup(patch.stopall)
        patch.object(gate, 'MANIFEST_SHA256', manifest_sha).start()
        patch.object(gate, 'CONTEXT_SHA256', context_sha).start()
        self.persist()

    def persist(self):
        save(self.root / 'matrix.json', self.matrix)
        self.matrix_sha = gate.sha(self.root / 'matrix.json')
        self.marker['matrix_sha256'] = self.matrix_sha
        save(self.root / 'MATRIX_COMPLETE.json', self.marker)
        save(self.root / 'status.json', self.status)

    def test_live_or_failed_attempt_is_rejected_before_reading_a_live_ledger(self):
        save(self.root / 'matrix.json', {'must_not_be_opened': True})
        with patch.object(gate, 'read', side_effect=AssertionError('live ledger opened')):
            with self.assertRaisesRegex(ValueError, 'partial/live'): gate.terminal_documents(self.root, '0' * 64)
        self.terminal_fixture(); save(self.root / 'FAILED.json', {})
        with self.assertRaisesRegex(ValueError, 'partial/live'): gate.terminal_documents(self.root, self.matrix_sha)

    def test_valid_complete_boundary_preserves_false_runtime_and_financial_flags(self):
        self.terminal_fixture()
        manifest, matrix = gate.terminal_documents(self.root, self.matrix_sha)
        self.assertEqual(100, len(matrix['scope_records']))
        self.assertIs(False, matrix['runtime_admission_ready'])
        self.assertIs(False, manifest['financial_validation_started'])

    def test_counts_and_terminal_state_cannot_be_replaced_by_intent(self):
        self.terminal_fixture()
        for changed in (dict(state='RUNNING'), dict(completed_groups=19), dict(completed_scopes=99), dict(total_scopes=101)):
            original = self.status.copy(); self.status.update(changed); self.persist()
            with self.assertRaises(ValueError): gate.terminal_documents(self.root, self.matrix_sha)
            self.status = original

    def test_external_matrix_pin_and_raw_manifest_hash_are_mandatory(self):
        self.terminal_fixture()
        for digest in ('0' * 64, '', None, 'G' * 64):
            with self.assertRaises(ValueError): gate.terminal_documents(self.root, digest)
        (self.root / 'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'digest changed'): gate.terminal_documents(self.root, self.matrix_sha)

    def test_missing_or_true_flags_never_become_training_only_evidence(self):
        self.terminal_fixture()
        original = copy.deepcopy(self.matrix)
        for name in ('runtime_reuse_enabled', 'runtime_admission_ready', 'financial_validation_started', 'new_holdout_read', 'production_write'):
            for value in (None, True, 0):
                self.matrix = copy.deepcopy(original); self.matrix[name] = value; self.persist()
                with self.assertRaisesRegex(ValueError, 'training-only'): gate.terminal_documents(self.root, self.matrix_sha)

    def test_a_hundred_names_do_not_substitute_for_twenty_real_reference_bindings(self):
        self.terminal_fixture(); self.matrix['canonical_references'].pop(); self.persist()
        with self.assertRaisesRegex(ValueError, 'all20'): gate.terminal_documents(self.root, self.matrix_sha)

    def test_changed_scope_or_nonzero_coverage_count_is_rejected(self):
        self.terminal_fixture(); self.matrix['scope_records'][0]['side'] *= -1; self.persist()
        with self.assertRaises(ValueError): gate.terminal_documents(self.root, self.matrix_sha)
        self.terminal_fixture(); self.marker['nonzero_reference_groups'] = 19; self.persist()
        with self.assertRaisesRegex(ValueError, 'coverage count'): gate.terminal_documents(self.root, self.matrix_sha)

    def test_complete_reader_checks_all_twenty_groups_and_environment_twice(self):
        self.terminal_fixture()
        with patch.object(gate, 'require_environment') as environment, patch.object(gate, 'verify_group') as group:
            audit = gate.verify_complete_matrix(self.root, self.matrix_sha, object())
            self.assertEqual(20, group.call_count); self.assertEqual(2, environment.call_count)
            self.assertEqual(100, audit['verified_training_scopes'])
            self.assertIs(False, audit['runtime_reuse_enabled']); self.assertIs(False, audit['financial_validation_started'])

    def test_terminal_data_change_during_read_is_rejected_by_final_boundary_check(self):
        self.terminal_fixture()
        def change(*args):
            (self.root / 'matrix.json').write_text('{}')
        with patch.object(gate, 'require_environment'), patch.object(gate, 'verify_group', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'digest changed'):
                gate.verify_complete_matrix(self.root, self.matrix_sha, object())

    def group_fixture(self):
        queue, _, _ = matrix_tests.CusumIdentityMatrixTest().records()
        rows = gate.group_scopes(queue)[0][1]; records = []
        profile = {'minForwardContribution': .2, 'fitWindowDays': 90}
        for row in rows:
            name = row['strategy']; frozen = self.root / 'frozen' / name; frozen.mkdir(parents=True)
            source = frozen / 'GeneratedStrategy.java'; source.write_text(fixture_source(name), encoding='utf-8')
            seed = frozen / 'seed.json'; save(seed, {'strategies': [dict(strategyName=name, symbol=row['symbol'], scene=row['scene'],
                request=dict(optimizationProfile=profile, parameterSchema={}, defaultParameters={}))]})
            artifact = self.root / 'artifacts' / name / 'strategy.jar'; artifact.parent.mkdir(parents=True)
            with zipfile.ZipFile(artifact, 'w') as jar:
                jar.writestr('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\n')
                for suffix in ('', '$Quotes', '$1'):
                    jar.writestr(identity_prefix(name) + 'GeneratedStrategy' + suffix + '.class', fixture_class(name))
            validator = self.root / 'logs' / (name + '-validator.log'); validator.parent.mkdir(exist_ok=True); validator.write_text('fixture')
            records.append(dict(row, source_path=str(source), source_sha256=gate.sha(source), seed_path=str(seed),
                seed_sha256=gate.sha(seed), artifact_path=str(artifact), artifact_sha256=gate.sha(artifact),
                entry_class=identity_prefix(name).replace('/', '.') + 'GeneratedStrategy',
                validator_log_path=str(validator), validator_log_sha256=gate.sha(validator),
                optimization_profile_sha256=gate.digest_json(profile), context_sha256=gate.CONTEXT_SHA256,
                training_bars=35040, training_signals=10, mismatches=0, runtime_reuse_enabled=False,
                financial_validation_started=False, production_write=False))
        canonical = copy.deepcopy(records[0]); log = self.root / 'logs' / 'canonical.log'
        log.write_text('bars=35040, researchSignals=10, exportedSignals=10, mismatches=0')
        canonical.update(actual_full_year_replay=True, full_year_log_path=str(log), full_year_log_sha256=gate.sha(log))
        group = self.root / 'groups' / canonical['symbol'] / 'long'; save(group / 'canonical.json', canonical)
        for record in records:
            record['identity_proof'] = require_jar_identity_equivalence(Path(canonical['artifact_path']), canonical['strategy'],
                Path(record['artifact_path']), record['strategy'])
            save(group / (record['strategy'] + '.json'), record)
        marker = dict(matrix_manifest_sha256=gate.MANIFEST_SHA256, context_sha256=gate.CONTEXT_SHA256,
            completed_scopes=5, actual_full_year_replays=1, canonical_sha256=gate.sha(group / 'canonical.json'),
            scope_proof_sha256={r['strategy']: gate.sha(group / (r['strategy'] + '.json')) for r in records},
            runtime_reuse_enabled=False, production_write=False)
        save(group / 'GROUP_COMPLETE.json', marker)
        return rows, canonical, records

    def verify_group(self, values):
        gate.verify_group(self.root, *values, gate.MANIFEST_SHA256, gate.CONTEXT_SHA256)

    def test_group_audit_uses_real_file_hashes_and_three_class_comparison(self):
        values = self.group_fixture(); self.verify_group(values)
        Path(values[2][-1]['artifact_path']).write_bytes(b'changed')
        with self.assertRaises(ValueError): self.verify_group(values)

    def test_incomplete_group_and_changed_full_year_log_are_rejected(self):
        rows, canonical, records = self.group_fixture()
        with self.assertRaises(ValueError): self.verify_group((rows, canonical, records[:-1]))
        Path(canonical['full_year_log_path']).write_text('bars=35040, researchSignals=11, exportedSignals=11, mismatches=0')
        with self.assertRaisesRegex(ValueError, 'full-year'): self.verify_group((rows, canonical, records))

    def test_exact_scope_requires_current_source_and_complete_scene_seed(self):
        rows, _, records = self.group_fixture(); row, record = rows[0], records[0]
        source, seed = Path(record['source_path']), Path(record['seed_path'])
        result = gate.require_exact_scope(record, row, source, seed)
        self.assertIs(False, result['runtime_reuse_enabled'])
        for changed in (dict(row, symbol='OTHERUSDT'), dict(row, scene='range'), dict(row, side=-row['side'])):
            with self.assertRaises(ValueError): gate.require_exact_scope(record, changed, source, seed)
        seed.write_text('{}')
        with self.assertRaises(ValueError): gate.require_exact_scope(record, row, source, seed)

    def test_paths_outside_frozen_artifact_roots_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError, 'escaped'):
            gate.require_inside(self.root, self.root.parent / 'unrelated.jar', 'artifacts')

    def test_runtime_membership_executable_and_option_checks_are_not_omitted(self):
        args = SimpleNamespace(sim_repo=self.root / 'sim')
        selected = str((self.root / 'java').resolve())
        context = dict(runtime_jar_sha256={}, classpath_class_sha256={}, critical_sha256={selected: 'hash'}, training_sha256={},
            java_option_environment_sha256={k: gate.hashlib.sha256(os.environ.get(k, '').encode()).hexdigest()
                for k in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')})
        with patch.object(gate, 'CONTEXT_SHA256', gate.digest_json(context)), patch.object(gate, 'classpath_classes', return_value={}), \
                patch.object(gate.shutil, 'which', return_value=selected), patch.object(gate, 'require_hashes') as hashes:
            gate.require_environment(context, args); self.assertEqual(3, hashes.call_count)
            with patch.dict(os.environ, {'JAVA_TOOL_OPTIONS': '-Dchanged=true'}):
                with self.assertRaisesRegex(ValueError, 'option environment'): gate.require_environment(context, args)
            with patch.object(gate.shutil, 'which', return_value=str(self.root / 'other-java')):
                with self.assertRaisesRegex(ValueError, 'selection changed'): gate.require_environment(context, args)
            with patch.object(gate, 'classpath_classes', return_value={'extra.class': 'hash'}):
                with self.assertRaisesRegex(ValueError, 'classpath'): gate.require_environment(context, args)


if __name__ == '__main__': unittest.main()
