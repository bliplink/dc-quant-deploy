import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import psutil

from recovery.research_control_handoff import drain_and_stop, identity, require_local_research_parent, read


def wait_for_fixture_state(pid, created, state, timeout=10):
    """Observe the actual OS state; a preceding ledger write is not a state barrier."""
    deadline = time.monotonic() + timeout
    while True:
        process = psutil.Process(pid)
        if process.create_time() != created:
            raise AssertionError('fixture PID identity changed')
        if process.status() == state:
            return
        if time.monotonic() >= deadline:
            raise AssertionError('fixture did not reach OS state: ' + state)
        time.sleep(.02)


class ResearchControlHandoffTest(unittest.TestCase):
    def test_fixture_state_barrier_waits_for_os_observation_not_a_ledger_marker(self):
        process = Mock(); process.create_time.return_value = 10.5
        process.status.side_effect = [psutil.STATUS_RUNNING, psutil.STATUS_STOPPED]
        with patch(__name__ + '.psutil.Process', return_value=process), \
             patch(__name__ + '.time.sleep') as sleep:
            wait_for_fixture_state(10, 10.5, psutil.STATUS_STOPPED)
        self.assertEqual(2, process.status.call_count); sleep.assert_called_once_with(.02)

    def test_fixture_state_barrier_rejects_reused_pid(self):
        process = Mock(); process.create_time.return_value = 99.5
        with patch(__name__ + '.psutil.Process', return_value=process):
            with self.assertRaisesRegex(AssertionError, 'identity changed'):
                wait_for_fixture_state(10, 10.5, psutil.STATUS_STOPPED)
        process.status.assert_not_called()

    def test_only_transient_permission_reads_are_bounded_operational_retries(self):
        with patch('recovery.research_control_handoff.raw_read', side_effect=[PermissionError(13, 'sharing'), {'phase': 'READY'}]) as source, \
             patch('recovery.research_control_handoff.time.sleep'):
            self.assertEqual({'phase': 'READY'}, read('metadata'))
            self.assertEqual(2, source.call_count)
        with patch('recovery.research_control_handoff.raw_read', side_effect=PermissionError(13, 'persistent')) as source, \
             patch('recovery.research_control_handoff.time.sleep'):
            with self.assertRaises(PermissionError): read('metadata')
            self.assertEqual(8, source.call_count)

    def test_corrupt_metadata_is_not_retried_or_substituted(self):
        with patch('recovery.research_control_handoff.raw_read', side_effect=ValueError('corrupt')) as source:
            with self.assertRaises(ValueError): read('metadata')
            self.assertEqual(1, source.call_count)

    def test_only_exact_local_wrapper_identity_is_accepted(self):
        with patch('recovery.research_control_handoff.psutil.Process') as cls:
            process = cls.return_value
            process.pid = 123
            process.create_time.return_value = 456
            process.cmdline.return_value = ['python', '-m', 'recovery.run_fit_risk_catalog_batch',
                                            '--output-dir', str(Path.cwd())]
            process.is_running.return_value = True
            process.status.return_value = psutil.STATUS_RUNNING
            self.assertEqual(123, require_local_research_parent(123, Path.cwd())['pid'])
            for command in (['python', '-m', 'wrong', '--output-dir', str(Path.cwd())],
                            ['python', '-m', 'recovery.run_fit_risk_catalog_batch', '--output-dir', str(Path.cwd() / 'wrong')]):
                process.cmdline.return_value = command
                with self.assertRaises(ValueError):
                    require_local_research_parent(123, Path.cwd())

    def test_changed_pid_identity_prevents_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('recovery.research_control_handoff.parent_alive', return_value=False):
                with self.assertRaisesRegex(ValueError, 'identity changed'):
                    drain_and_stop({}, Path(directory), Mock())
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_actual_local_child_finishes_before_control_parent_is_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_code = "import time; from pathlib import Path; time.sleep(.5); Path(%r).write_text('done')" % str(root / 'CHILD_DONE')
            parent_code = ("import subprocess,sys,time; from pathlib import Path; "
                "p=subprocess.Popen([sys.executable,'-c',%r]); Path(%r).write_text(str(p.pid)); "
                "p.wait(); time.sleep(10); Path(%r).write_text('must not start')") % (
                    child_code, str(root / 'CHILD_PID'), str(root / 'NEXT_STARTED'))
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            parent = subprocess.Popen([sys.executable, '-c', parent_code], creationflags=flags)
            try:
                deadline = time.monotonic() + 10
                while not (root / 'CHILD_PID').exists():
                    if time.monotonic() > deadline:
                        self.fail('fixture child did not start')
                    time.sleep(.02)
                bound = identity(psutil.Process(parent.pid))

                def checkpoint():
                    self.assertTrue((root / 'CHILD_DONE').exists())
                    self.assertFalse((root / 'NEXT_STARTED').exists())
                    return {'completed': 1, 'financial_replay_performed': False}

                result = drain_and_stop(bound, root, checkpoint, timeout=15)
                self.assertEqual(1, result['completed'])
                parent.wait(timeout=5)
                self.assertFalse((root / 'NEXT_STARTED').exists())
                intent = read(root / 'HANDOFF_INTENT.json')
                self.assertEqual('TRANSFERRED', intent['phase'])
                self.assertFalse(intent['children_stopped'])
                # Guardian exits after observing the transferred/dead parent.
                time.sleep(.35)
            finally:
                if parent.poll() is None:
                    psutil.Process(parent.pid).resume()
                    parent.terminate()
                    parent.wait(timeout=5)

    def test_failed_checkpoint_restores_parent_instead_of_terminating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                bound = identity(psutil.Process(parent.pid))
                with self.assertRaisesRegex(ValueError, 'partial checkpoint'):
                    drain_and_stop(bound, root, Mock(side_effect=ValueError('partial checkpoint')))
                self.assertIsNone(parent.poll())
                self.assertNotEqual(psutil.STATUS_STOPPED, psutil.Process(parent.pid).status())
                self.assertEqual('ABORTED', read(root / 'HANDOFF_INTENT.json')['phase'])
            finally:
                parent.terminate()
                parent.wait(timeout=5)

    def test_guardian_restores_exact_parent_when_handoff_owner_exits_abruptly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], creationflags=flags)
            owner = None
            try:
                bound = identity(psutil.Process(parent.pid))
                code = ('import json,time; from pathlib import Path; '
                    'from recovery.research_control_handoff import drain_and_stop; '
                    'drain_and_stop(json.loads(%r),Path(%r),lambda:time.sleep(30))') % (
                        json.dumps(bound), str(root))
                owner = subprocess.Popen([sys.executable, '-c', code], creationflags=flags)
                deadline = time.monotonic() + 10
                while not (root / 'HANDOFF_CHECKPOINT.json').exists():
                    intent_path = root / 'HANDOFF_INTENT.json'
                    if intent_path.exists() and read(intent_path)['phase'] == 'DRAINING':
                        break
                    if owner.poll() is not None or time.monotonic() > deadline:
                        self.fail('handoff fixture never suspended its parent')
                    time.sleep(.02)
                wait_for_fixture_state(parent.pid, bound['create_time'], psutil.STATUS_STOPPED)
                self.assertEqual(psutil.STATUS_STOPPED, psutil.Process(parent.pid).status())
                owner.terminate()
                owner.wait(timeout=5)
                deadline = time.monotonic() + 5
                while not (root / 'GUARDIAN_RESTORED.json').exists():
                    if time.monotonic() > deadline:
                        self.fail('guardian failed to restore original wrapper')
                    time.sleep(.02)
                self.assertIsNone(parent.poll())
                self.assertNotEqual(psutil.STATUS_STOPPED, psutil.Process(parent.pid).status())
                guard_id = read(root / 'GUARDIAN_READY.json')['guardian']['pid']
                try:
                    psutil.Process(guard_id).wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
            finally:
                if owner and owner.poll() is None:
                    owner.terminate()
                    owner.wait(timeout=5)
                # Join only this fixture's exact guardian while its exact parent
                # still exists. Do not race TempDirectory cleanup against its log.
                ready_path = root / 'GUARDIAN_READY.json'
                if ready_path.exists():
                    guardian = read(ready_path)['guardian']
                    try:
                        guard = psutil.Process(guardian['pid'])
                        if guard.create_time() != guardian['create_time'] or guard.cmdline() != guardian['command']:
                            raise AssertionError('fixture guardian PID identity changed')
                        guard.wait(timeout=10)
                    except psutil.NoSuchProcess:
                        pass
                if parent.poll() is None:
                    process = psutil.Process(parent.pid)
                    if process.create_time() != bound['create_time']:
                        raise AssertionError('fixture parent PID identity changed')
                    process.resume()
                    parent.terminate()
                    parent.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
