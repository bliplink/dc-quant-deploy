import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from recovery.watch_fixed_primary_supplements import (
    coherent_parent_snapshot, completed_parent, parent_alive, parent_identity, verified_supplement,
)
from recovery.verify_fit_only_risk_contract import sha
from recovery import test_temporal_admission_contract as temporal_fixture


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class FixedPrimaryWatcherTest(unittest.TestCase):
    def test_parent_must_match_module_path_and_creation_time_not_just_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory).resolve() / 'formal'
            process = Mock()
            process.cmdline.return_value = ['python', '-m', 'recovery.run_representative_reserve_cycle',
                                            '--output-dir', str(formal.parent)]
            process.create_time.return_value = 123
            process.is_running.return_value = True
            with patch('recovery.watch_fixed_primary_supplements.psutil.Process', return_value=process):
                identity = parent_identity(42, formal)
                self.assertTrue(parent_alive(identity))
                process.create_time.return_value = 124
                self.assertFalse(parent_alive(identity))
                process.cmdline.return_value = ['python', '-m', 'other.tool', '--output-dir', str(formal.parent)]
                with self.assertRaisesRegex(ValueError, 'identity'):
                    parent_identity(42, formal)

    def test_torn_legacy_status_then_result_is_waited_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = {'completed': 2, 'total': 2, 'local_formal_qualified': 1, 'errors': []}
            first = {'strategy': 'first', 'qualified': False}
            second = {'strategy': 'second', 'qualified': True}
            write(root / 'status.json', status)
            write(root / 'results.json', [first])
            self.assertIsNone(coherent_parent_snapshot(root))
            (root / 'results.json').write_text('[{"strategy":', encoding='utf-8')
            self.assertIsNone(coherent_parent_snapshot(root))
            write(root / 'results.json', [first, second])
            self.assertEqual([first, second], coherent_parent_snapshot(root)[1])
            write(root / 'status.json', dict(status, errors=['execution failed']))
            with self.assertRaisesRegex(ValueError, 'execution/parity'):
                coherent_parent_snapshot(root)

    def test_completion_requires_all_original_outcomes_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [{'strategy': 'one', 'qualified': False}]
            status = {'completed': 1, 'total': 1, 'local_formal_qualified': 0}
            write(root / 'manifest.json', {'target_candidates': 1})
            self.assertFalse(completed_parent(root, status, records))
            marker = {'manifest_sha256': sha(root / 'manifest.json'), 'completed': 1,
                      'local_formal_qualified': 0, 'production_write': False}
            write(root / 'FORMAL_COMPLETE.json', marker)
            self.assertTrue(completed_parent(root, status, records))
            with self.assertRaisesRegex(ValueError, 'every financial'):
                completed_parent(root, dict(status, total=2), records)

    def test_reusing_failed_supplement_preserves_result_and_exact_original_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.java'
            source.write_bytes(b'fixed source\n')
            original_file = root / 'original.json'
            write(original_file, {'original': 'financial observation'})
            original = {'strategy': 'fixed', 'source_sha256': sha(source), 'symbol': 'SOLUSDT', 'scene': 'range',
                        'hypothesis': 'median', 'family': 'CatalogAtrExitMedian', 'result_path': str(original_file)}
            bindings = dict(protocol_sha256='protocol', ready_sha256='ready', oracle_manifest_sha256='oracle',
                            helper_source_sha256='helper')
            out = root / 'supplement'
            manifest = dict(bindings, strategy='fixed', source_sha256=sha(source),
                primary_envelope_sha256=sha(original_file), primary_pnl_rerun=False, production_write=False)
            write(out / 'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'partial'):
                verified_supplement(out, original, bindings)
            admission = temporal_fixture.TemporalAdmissionTest().envelope()
            admission.update(sourceSha256=sha(source), sourceFile=str(source))
            admission['result'].update(selectedParameters={}, bestParamSetJson='{}', qualified=False)
            admission['result']['holdout'].update(lockedParameters={}, sourceSha256=sha(source), passed=False)
            write(out / 'admission.json', admission)
            record = dict(original, result_path=str(out / 'admission.json'), qualified=False)
            write(out / 'results.json', [record])
            write(out / 'FORMAL_COMPLETE.json', {'manifest_sha256': sha(out / 'manifest.json')})
            self.assertFalse(verified_supplement(out, original, bindings)['qualified'])
            source.write_bytes(b'changed source\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                verified_supplement(out, original, bindings)


if __name__ == '__main__':
    unittest.main()
