import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recovery.run_fit_risk_catalog_batch import (
    case_key, exclusive_batch, remaining_queue, resource_state, source_parent_identity, verify_full_source_proof)
from recovery.verify_fit_only_risk_contract import sha


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class FullCatalogBatchTest(unittest.TestCase):
    def test_cell_rotation_is_complete_balanced_and_deterministic(self):
        catalog = [dict(hypothesis='h' + str(i), family='f' + str(i // 2)) for i in range(12)]
        symbols = ['BBB', 'AAA']
        queue = remaining_queue(catalog, symbols, set())
        self.assertEqual(120, len(queue))
        self.assertEqual(10, len({(r['symbol'], r['scene']) for r in queue[:10]}))
        self.assertEqual(120, len({case_key(row) for row in queue}))
        self.assertEqual(queue, remaining_queue(catalog, list(reversed(symbols)), set()))
        self.assertTrue(all('riskProfile' not in row for row in queue))

    def test_reserved_and_consumed_scopes_are_removed_not_rerun(self):
        catalog = [dict(hypothesis='h' + str(i), family='f' + str(i // 2)) for i in range(400)]
        symbols = ['SYMBOL' + str(i) for i in range(10)]
        queue = remaining_queue(catalog, symbols, set())
        excluded = {case_key(row) for row in queue[:401]}
        remaining = remaining_queue(catalog, symbols, excluded)
        self.assertEqual(19599, len(remaining))
        self.assertEqual([row for row in queue if case_key(row) not in excluded], remaining)

    def test_duplicate_catalog_hypothesis_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            remaining_queue([dict(hypothesis='same', family='a'), dict(hypothesis='same', family='b')], ['BTC'], set())

    def test_live_os_lock_blocks_second_runner_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            with exclusive_batch(directory):
                with self.assertRaises(OSError):
                    with exclusive_batch(directory):
                        self.fail('second runner entered a held lock')
            with exclusive_batch(directory):
                pass

    def test_source_parent_requires_exact_module_and_output(self):
        with patch('recovery.run_fit_risk_catalog_batch.psutil.Process') as process:
            process.return_value.cmdline.return_value = ['python', '-m', 'recovery.verify_fit_risk_catalog',
                                                          '--output-dir', str(Path.cwd())]
            process.return_value.create_time.return_value = 123.5
            process.return_value.is_running.return_value = True
            identity = source_parent_identity(321, Path.cwd())
            self.assertEqual(123.5, identity['create_time'])
            self.assertEqual(321, identity['pid'])
            with self.assertRaisesRegex(ValueError, 'identity'):
                source_parent_identity(321, Path.cwd() / 'wrong')
            process.return_value.cmdline.return_value = ['python', '-m', 'wrong', '--output-dir', str(Path.cwd())]
            with self.assertRaisesRegex(ValueError, 'identity'):
                source_parent_identity(321, Path.cwd())

    def test_resource_guard_does_not_fill_disk_or_start_when_memory_is_low(self):
        with patch('recovery.run_fit_risk_catalog_batch.shutil.disk_usage') as disk:
            with patch('recovery.run_fit_risk_catalog_batch.psutil.virtual_memory') as memory:
                disk.return_value.free = 8 * 1024 ** 3
                memory.return_value.available = 1536 * 1024 ** 2
                self.assertTrue(resource_state(Path.cwd())['ready'])
                disk.return_value.free -= 1
                self.assertFalse(resource_state(Path.cwd())['ready'])
                disk.return_value.free += 1
                memory.return_value.available -= 1
                self.assertFalse(resource_state(Path.cwd())['ready'])

    def test_full_source_proof_rejects_incomplete_or_failed_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / 'manifest.json', {'catalog': []})
            marker = {'completed': 399, 'profile_cases': 1596, 'manifest_sha256': sha(root / 'manifest.json'),
                      'financial_validation_started': False, 'production_write': False}
            write(root / 'SOURCE_CONTRACT_COMPLETE.json', marker)
            with self.assertRaisesRegex(ValueError, '400-source'):
                verify_full_source_proof(root)
            write(root / 'SOURCE_CONTRACT_COMPLETE.json', dict(marker, completed=400, profile_cases=1600))
            write(root / 'FAILED.json', {'error': 'preserved failure'})
            with self.assertRaisesRegex(ValueError, '400-source'):
                verify_full_source_proof(root)

    def test_all_400_contracts_and_each_artifact_hash_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = [dict(hypothesis='h' + str(i), family='f') for i in range(400)]
            write(root / 'manifest.json', {'catalog': catalog})
            digest = sha(root / 'manifest.json')
            write(root / 'SOURCE_CONTRACT_COMPLETE.json', {'completed': 400, 'profile_cases': 1600,
                'manifest_sha256': digest, 'financial_validation_started': False, 'production_write': False})
            artifact = root / 'proof.jar'
            artifact.write_bytes(b'fixed bytecode fixture')
            for row in catalog:
                name = row['hypothesis']
                source = root / 'frozen' / name / 'GeneratedStrategy.java'
                source.parent.mkdir(parents=True)
                source.write_bytes(b'fixed source fixture')
                write(root / 'artifacts' / name / 'contract.json', dict(row, strategy=name,
                    manifest_sha256=digest, artifact_path=str(artifact), artifact_sha256=sha(artifact),
                    source_sha256=sha(source), source_validator_passed=True,
                    profiles=[dict(risk_profile=i, bars=35040, mismatches=0) for i in range(4)]))
            self.assertEqual(400, len(verify_full_source_proof(root)['contracts_sha256']))
            artifact.write_bytes(b'changed bytecode')
            with self.assertRaisesRegex(ValueError, 'proof changed'):
                verify_full_source_proof(root)


if __name__ == '__main__':
    unittest.main()
