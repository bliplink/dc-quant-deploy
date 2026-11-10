from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from recovery import run_directional_clock_parallel as parallel
from recovery import retire_directional_clock_waiter as retirement
from recovery.run_fit_risk_catalog_batch import exclusive_batch
from recovery.verify_fit_only_risk_contract import sha


class DirectionalClockParallelTest(unittest.TestCase):
    def fixture(self, root):
        original = root / 'strategy-directional-clock-original'; original.mkdir()
        parent = root / 'profile-parent'; parent.mkdir()
        command = ['python', '-u', '-m', parallel.ORIGINAL_MODULE]
        for name in parallel.CONTEXT_PATHS:
            command += ['--' + name, str(root / name)]
        command += ['--output-dir', str(original), '--wait-for-parent-pid', '20', '--wait-for-parent-dir', str(parent)]
        parent_command = ['python', '-u', '-m', 'recovery.run_ohlcv_profile_proxy_batch', '--output-dir', str(parent)]
        manifest = dict(schema='frozen_directional_clock_100_scopes_v1', queue=[{'strategy': 's' + str(i)} for i in range(100)],
                        parent_identity=dict(pid=20, create_time=20.5, command=parent_command, output_dir=str(parent)))
        (original / 'manifest.json').write_text(json.dumps(manifest))
        (original / 'status.json').write_text(json.dumps(dict(state='WAITING_FOR_BOUND_PROFILE_BATCH', completed=0, total=100)))
        (parent / 'status.json').write_text(json.dumps(dict(state='RUNNING', completed=15, total=200)))
        owner = Mock(); owner.create_time.return_value = 10.5; owner.cmdline.return_value = command; owner.children.return_value = []
        parent_owner = Mock(); parent_owner.create_time.return_value = 20.5; parent_owner.cmdline.return_value = parent_command
        return original, manifest, command, owner, parent_owner

    def test_exact_original_command_options_and_entire_policy_context_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); original, _, command, _, _ = self.fixture(root)
            context = parallel.original_context(command, original)
            self.assertEqual((root / 'protocol').resolve(), context.protocol)
            with self.assertRaises(ValueError): parallel.original_context(command + ['--protocol', 'changed'], original)
            with self.assertRaises(ValueError): parallel.original_context(command, root / 'another-scope')
            with self.assertRaises(ValueError): parallel.original_context(['python', '-m', 'other'], original)

    def test_zero_counter_cannot_hide_started_source_or_financial_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            original, _, _, _, _ = self.fixture(Path(temporary)); digest = sha(original / 'manifest.json')
            parallel.require_zero_finance(original, digest)
            (original / 'candidates').mkdir()
            with self.assertRaisesRegex(ValueError, 'already started'): parallel.require_zero_finance(original, digest)

    def test_completed_failed_or_changed_original_plan_is_not_migratable(self):
        with tempfile.TemporaryDirectory() as temporary:
            original, _, _, _, _ = self.fixture(Path(temporary)); digest = sha(original / 'manifest.json')
            with self.assertRaises(ValueError): parallel.require_zero_finance(original, 'changed')
            (original / 'FAILED.json').write_text('{}')
            with self.assertRaises(ValueError): parallel.require_zero_finance(original, digest)

    def test_idle_identity_requires_creation_time_and_no_calculation_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            original, _, _, owner, parent = self.fixture(Path(temporary)); digest = sha(original / 'manifest.json')
            with patch.object(parallel.psutil, 'Process', side_effect=lambda pid: owner if pid == 10 else parent):
                self.assertIs(owner, parallel.observe_idle(original, digest, 10, 10.5)[0])
                with self.assertRaisesRegex(ValueError, 'reused'): parallel.observe_idle(original, digest, 10, 10.6)
                child = Mock(); child.name.return_value = 'java.exe'; owner.children.return_value = [child]
                with self.assertRaisesRegex(ValueError, 'calculation child'): parallel.observe_idle(original, digest, 10, 10.5)
                owner.terminate.assert_not_called()

    def test_nearly_completed_or_failed_parent_cannot_release_waiter_during_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); original, manifest, _, owner, parent = self.fixture(root); digest = sha(original / 'manifest.json')
            (root / 'profile-parent/status.json').write_text(json.dumps(dict(completed=200, total=200)))
            with patch.object(parallel.psutil, 'Process', side_effect=lambda pid: owner if pid == 10 else parent):
                with self.assertRaisesRegex(ValueError, 'parent may release'): parallel.observe_idle(original, digest, 10, 10.5)
                owner.terminate.assert_not_called()

    def test_extra_slot_preserves_original_guards_and_requires_three_gib(self):
        with patch.object(parallel, 'resource_state', return_value={'ready': True}), \
             patch.object(parallel.psutil, 'virtual_memory', return_value=Namespace(available=3072 * 1048576)), \
             patch.object(parallel.psutil, 'cpu_count', return_value=8):
            self.assertTrue(parallel.extra_slot_resources(Path('.'), 3072)['ready'])
            with self.assertRaises(ValueError): parallel.extra_slot_resources(Path('.'), 3071)
        with patch.object(parallel, 'resource_state', return_value={'ready': False}), \
             patch.object(parallel.psutil, 'virtual_memory', return_value=Namespace(available=4096 * 1048576)), \
             patch.object(parallel.psutil, 'cpu_count', return_value=8):
            self.assertFalse(parallel.extra_slot_resources(Path('.'), 3072)['ready'])
        with patch.object(parallel, 'resource_state', return_value={'ready': True}), \
             patch.object(parallel.psutil, 'virtual_memory', return_value=Namespace(available=3071 * 1048576)), \
             patch.object(parallel.psutil, 'cpu_count', return_value=8):
            self.assertFalse(parallel.extra_slot_resources(Path('.'), 3072)['ready'])

    def test_new_owner_rejects_live_old_owner_but_not_a_reused_pid(self):
        record = dict(schema='zero_finance_clock_scheduling_handoff_v1', old_identity=dict(pid=10, create_time=10.5),
                      original_completed=0, calculation_children=[], financial_dispatch_ever_started=False, old_owner_stop_verified=True)
        with patch.object(parallel.psutil, 'pid_exists', return_value=True), patch.object(parallel.psutil, 'Process') as process:
            process.return_value.create_time.return_value = 10.5
            with self.assertRaisesRegex(ValueError, 'still lives'): parallel.require_old_owner_stopped(record)
            process.return_value.create_time.return_value = 99.5; parallel.require_old_owner_stopped(record)
        with patch.object(parallel.psutil, 'pid_exists', return_value=False):
            with self.assertRaises(ValueError): parallel.require_old_owner_stopped(dict(record, original_completed=1))

    def prepare_retirement(self, root):
        original, manifest, command, owner, parent = self.fixture(root)
        preflight = root / 'preflight'; preflight.mkdir(); digest = sha(original / 'manifest.json')
        prepared = dict(original_manifest_sha256=digest,
            controller_source_sha256=sha(Path(parallel.__file__)), retirer_source_sha256=sha(Path(retirement.__file__)),
            entire_queue_scopes=100, source_and_helpers_unchanged=True, financial_dispatch_started=False,
            checked_tool_sha256={}, production_write=False)
        (preflight / 'PREPARE_COMPLETE.json').write_text(json.dumps(prepared))
        return original, manifest, owner, preflight, digest

    def test_retirement_reevaluates_after_preflight_before_any_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); original, manifest, owner, preflight, digest = self.prepare_retirement(root)
            with patch.object(retirement, 'observe_idle', side_effect=[(owner, manifest, {'state': 'WAITING_FOR_BOUND_PROFILE_BATCH'}), ValueError('child began')]), \
                 patch.object(retirement, 'verify_context'):
                with self.assertRaisesRegex(ValueError, 'child began'):
                    retirement.retire(original, digest, 10, 10.5, preflight, root / 'strategy-directional-clock-parallel')
                owner.terminate.assert_not_called()

    def test_retirement_only_stops_exact_reobserved_idle_owner_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); original, manifest, owner, preflight, digest = self.prepare_retirement(root)
            with patch.object(retirement, 'observe_idle', return_value=(owner, manifest, {'state': 'WAITING_FOR_BOUND_PROFILE_BATCH'})), \
                 patch.object(retirement, 'verify_context'):
                record = retirement.retire(original, digest, 10, 10.5, preflight, root / 'strategy-directional-clock-parallel')
            owner.terminate.assert_called_once_with(); owner.wait.assert_called_once_with(timeout=20)
            self.assertEqual(0, record['original_completed']); self.assertFalse(record['financial_dispatch_ever_started'])
            self.assertEqual(digest, sha(original / 'manifest.json'))
            self.assertTrue((original / 'ORCHESTRATION_HANDOFF.json').exists())

    def test_original_and_new_root_locks_reject_accidental_old_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); old, new = root / 'old', root / 'new'; old.mkdir(); new.mkdir()
            with exclusive_batch(old), exclusive_batch(new):
                with self.assertRaises((ValueError, OSError)):
                    with exclusive_batch(old): self.fail('original scope must stay exclusively owned')


if __name__ == '__main__': unittest.main()
