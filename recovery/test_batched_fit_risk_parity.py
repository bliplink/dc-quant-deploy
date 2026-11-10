import unittest
import json
from pathlib import Path
import tempfile

from recovery.verify_batched_fit_risk_parity import batched_profiles, parity_summary
from recovery.prepare_fit_risk_scope_contract_batched import require_batching_proof
from recovery.verify_fit_only_risk_contract import sha


class BatchedFitRiskParityTest(unittest.TestCase):
    @staticmethod
    def summary(signals=17):
        return 'bars=35040, researchSignals=%d, exportedSignals=%d, mismatches=0, economics={null=%d}' % (signals, signals, signals)

    def output(self):
        return 'candidate source validation passed\n' + ''.join(
            'RISK_PROFILE_BEGIN %d\n%s\nRISK_PROFILE_END %d\n' % (p, self.summary(), p) for p in range(4))

    def test_exact_original_summaries_and_all_profiles_are_retained(self):
        result = batched_profiles(self.output())
        self.assertEqual([0, 1, 2, 3], [row['risk_profile'] for row in result])
        self.assertTrue(all(row['signals'] == 17 and row['economics'] == '{null=17}' for row in result))

    def test_zero_signals_are_explicit_not_claimed_as_positive_coverage(self):
        self.assertEqual(0, parity_summary(self.summary(0))['signals'])

    def test_missing_duplicate_reordered_or_unclosed_profiles_fail(self):
        for output in (self.output().replace('RISK_PROFILE_END 3', ''),
                       self.output().replace('RISK_PROFILE_BEGIN 2', 'RISK_PROFILE_BEGIN 1'),
                       self.output() + 'RISK_PROFILE_BEGIN 0\n',
                       self.output().replace('candidate source validation passed', '')):
            with self.assertRaises(ValueError):
                batched_profiles(output)

    def test_incomplete_year_mismatch_and_duplicate_summary_fail(self):
        for output in (self.summary().replace('35040', '35039'),
                       self.summary().replace('exportedSignals=17', 'exportedSignals=16'),
                       self.summary().replace('mismatches=0', 'mismatches=1'),
                       self.summary() + '\n' + self.summary()):
            with self.assertRaises(ValueError):
                parity_summary(output)

    def test_only_complete_source_bound_proof_and_unchanged_bytecode_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof, catalog, training, ind = [root / name for name in ('proof', 'catalog', 'training', 'ind')]

            def write(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding='utf-8')

            write(catalog / 'manifest.json', {})
            write(training / 'READY.json', {})
            original_cli = ind / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
            original_cli.parent.mkdir(parents=True)
            original_cli.write_bytes(b'original bytecode fixture')
            batch_class = proof / 'classes/Driver.class'
            batch_class.parent.mkdir(parents=True)
            batch_class.write_bytes(b'fixed batching bytecode fixture')
            cases, result_hashes = [], {}
            for i in range(8):
                name = 'case' + str(i)
                contract = root / name / 'contract.json'
                write(contract, {})
                case = {'strategy': name, 'contract_path': str(contract), 'contract_sha256': sha(contract)}
                cases.append(case)
                profiles = [dict(risk_profile=p, bars=35040, signals=17, mismatches=0) for p in range(4)]
                result = proof / 'cases' / name / 'result.json'
                write(result, dict(passed=True, profiles=profiles, original_profiles=profiles,
                                   new_holdout_read=False, production_write=False))
                result_hashes[name] = sha(result)
            java_dir = Path(__file__).with_name('java')
            manifest = dict(cases=cases, catalog_manifest_sha256=sha(catalog / 'manifest.json'),
                training_ready_sha256=sha(training / 'READY.json'),
                java_source_sha256=sha(java_dir / 'FourProfileParityBatchCli.java'),
                wrapper_sha256=sha(Path(__file__).with_name('verify_batched_fit_risk_parity.py')),
                reference_cli_sha256=sha(original_cli))
            write(proof / 'manifest.json', manifest)
            audit = dict(state='complete', cases=8, profile_cases=32,
                manifest_sha256=sha(proof / 'manifest.json'), class_sha256={'Driver.class': sha(batch_class)},
                result_sha256=result_hashes, financial_validation_started=False,
                new_holdout_read=False, production_write=False)
            write(proof / 'audit.json', audit)
            self.assertEqual(sha(proof / 'manifest.json'), require_batching_proof(proof, catalog, training, ind))
            for change in (dict(cases=7), dict(profile_cases=31), dict(new_holdout_read=True),
                           dict(financial_validation_started=True), dict(production_write=True)):
                write(proof / 'audit.json', dict(audit, **change))
                with self.assertRaises(ValueError):
                    require_batching_proof(proof, catalog, training, ind)
            write(proof / 'audit.json', audit)
            batch_class.write_bytes(b'changed bytecode')
            with self.assertRaisesRegex(ValueError, 'bytecode'):
                require_batching_proof(proof, catalog, training, ind)


if __name__ == '__main__':
    unittest.main()
