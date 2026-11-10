from argparse import Namespace
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from recovery.run_fit_risk_catalog_batch import case_key, remaining_queue
from recovery.run_fit_risk_catalog_batched import run_queue, scan_checkpoint, validate_queue


class BatchedCatalogControllerTest(unittest.TestCase):
    def test_exact_entire_queue_and_reservations_must_not_be_reranked_or_padded(self):
        catalog = [dict(hypothesis='h' + str(i), family='f' + str(i % 202)) for i in range(400)]
        symbols = ['SYMBOL' + str(i) for i in range(10)]
        full = remaining_queue(catalog, symbols, set())
        excluded = {case_key(row) for row in full[:401]}
        queue = remaining_queue(catalog, symbols, excluded)
        plan = dict(schema='frozen_remaining_fit_risk_catalog_v1', queue=queue,
                    server_codegen_allowed=False, production_write=False)
        validate_queue(plan, catalog, symbols, excluded)
        for changed in (list(reversed(queue)), queue[:-1], queue[:-1] + queue[:1]):
            with self.assertRaises(ValueError):
                validate_queue(dict(plan, queue=changed), catalog, symbols, excluded)

    def args(self, root):
        paths = {name: root / name for name in ('legacy_dir', 'catalog_dir', 'sim_repo', 'input_dir',
            'indsvr_repo', 'training_input_dir', 'batching_proof_dir', 'oracle_dir', 'output_dir')}
        paths['output_dir'].mkdir()
        paths['legacy_dir'].mkdir()
        (paths['legacy_dir'] / 'plan.json').write_text('{}')
        (paths['output_dir'] / 'manifest.json').write_text('{}')
        return Namespace(**paths, protocol=root / 'protocol.json', workers=1)

    def test_partial_financial_checkpoint_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            (args.legacy_dir / 'admissions' / 'one').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'partial/unknown financial'):
                scan_checkpoint(args, {'queue': [{'strategy': 'one'}]}, 'oracle')

    def test_all_completed_observations_are_reused_without_subprocesses(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            record = dict(strategy='one', qualified=False, strict_local_qualified=False)
            with patch('recovery.run_fit_risk_catalog_batched.subprocess.Popen') as start:
                run_queue(args, {'queue': [{'strategy': 'one'}]}, 'oracle', {'records': {'one': record}})
                start.assert_not_called()
            saved = json.loads((args.output_dir / 'results.json').read_text())
            self.assertEqual([record], saved)
            self.assertEqual('COMPLETE', json.loads((args.output_dir / 'status.json').read_text())['state'])

    def test_new_case_calls_original_financial_module_and_never_a_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            (args.legacy_dir / 'plan.json').parent.mkdir(parents=True, exist_ok=True)
            (args.legacy_dir / 'plan.json').write_text('{}')
            (args.output_dir / 'manifest.json').write_text('{}')
            item = dict(strategy='one', symbol='ETHUSDT', scene='range', hypothesis='frozen', family='family')
            contract = args.legacy_dir / 'contracts/one/artifacts/one/contract.json'
            contract.parent.mkdir(parents=True)
            contract.write_text('{}')
            record = dict(strategy='one', qualified=False, strict_local_qualified=False, reason='failed_gate')
            with patch('recovery.run_fit_risk_catalog_batched.subprocess.Popen') as start, \
                 patch('recovery.run_fit_risk_catalog_batched.verify_contract'), \
                 patch('recovery.run_fit_risk_catalog_batched.verified_observation', return_value=record), \
                 patch('recovery.run_fit_risk_catalog_batched.resource_state', return_value={
                     'ready': True, 'available_memory_bytes': 8 * 1024 ** 3}):
                start.return_value.pid = os.getpid()
                start.return_value.wait.return_value = 0
                run_queue(args, {'queue': [item]}, 'oracle', {'records': {}})
                self.assertEqual(1, start.call_count)
                command = start.call_args.args[0]
                self.assertEqual('recovery.run_fit_risk_admission', command[command.index('-m') + 1])
                self.assertEqual(str(args.legacy_dir / 'admissions/one'), command[command.index('--output-dir') + 1])
                start.return_value.kill.assert_not_called()
                start.return_value.terminate.assert_not_called()

    def test_partial_attempt_stops_dispatch_without_killing_or_retrying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            (args.legacy_dir / 'admissions/one').mkdir(parents=True)
            item = dict(strategy='one', symbol='ETHUSDT', scene='range', hypothesis='frozen', family='family')
            with patch('recovery.run_fit_risk_catalog_batched.subprocess.Popen') as start, \
                 patch('recovery.run_fit_risk_catalog_batched.resource_state', return_value={
                     'ready': True, 'available_memory_bytes': 8 * 1024 ** 3}):
                with self.assertRaisesRegex(ValueError, 'local execution failed'):
                    run_queue(args, {'queue': [item]}, 'oracle', {'records': {}})
                start.assert_not_called()
            self.assertTrue((args.output_dir / 'FAILED.json').exists())
            self.assertTrue((args.legacy_dir / 'admissions/one').is_dir())

    def test_two_workers_use_distinct_scopes_and_preserve_deterministic_ledger_order(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(Path(directory))
            args.workers = 2
            queue = [dict(strategy=name, symbol='ETHUSDT', scene='range', hypothesis=name, family='family')
                     for name in ('one', 'two')]
            for item in queue:
                contract = args.legacy_dir / 'contracts' / item['strategy'] / 'artifacts' / item['strategy'] / 'contract.json'
                contract.parent.mkdir(parents=True)
                contract.write_text('{}')
            barrier = threading.Barrier(2, timeout=5)

            def start(command, **kwargs):
                process = Mock(pid=os.getpid())
                process.wait.side_effect = lambda: (barrier.wait(), 0)[1]
                return process

            def result(_args, item, *_):
                return dict(strategy=item['strategy'], qualified=False, strict_local_qualified=False, reason='failed_gate')

            with patch('recovery.run_fit_risk_catalog_batched.subprocess.Popen', side_effect=start) as launch, \
                 patch('recovery.run_fit_risk_catalog_batched.verify_contract'), \
                 patch('recovery.run_fit_risk_catalog_batched.verified_observation', side_effect=result), \
                 patch('recovery.run_fit_risk_catalog_batched.resource_state', return_value={
                     'ready': True, 'available_memory_bytes': 8 * 1024 ** 3}):
                run_queue(args, {'queue': queue}, 'oracle', {'records': {}})
                self.assertEqual(2, launch.call_count)
                outputs = [call.args[0][call.args[0].index('--output-dir') + 1] for call in launch.call_args_list]
                self.assertEqual(2, len(set(outputs)))
            ledger = json.loads((args.output_dir / 'results.json').read_text())
            self.assertEqual(['one', 'two'], [row['strategy'] for row in ledger])


if __name__ == '__main__':
    unittest.main()
