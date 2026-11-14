import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class RecoveryEntryTest(unittest.TestCase):
    def entry(self, arguments, fail_first=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = root / 'calls.jsonl'
            config = root / 'ssh.config'
            config.write_text('fixture\n')
            for name, body in {'uname': 'echo Darwin', 'ssh': 'exit 0', 'curl': 'exit 0'}.items():
                command = root / name
                command.write_text('#!/bin/sh\n' + body + '\n')
                command.chmod(0o700)
            python = root / 'python3'
            python.write_text('#!/usr/bin/env python3-real\nimport json,os,sys\n'
                              'with open(os.environ["ENTRY_CALLS"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                              'sys.exit(23 if os.environ.get("ENTRY_FAIL_FIRST")=="yes" else 0)\n')
            # Use the current interpreter directly in the stub, avoiding recursive PATH lookup.
            import sys
            python.write_text(python.read_text().replace('/usr/bin/env python3-real', sys.executable))
            python.chmod(0o700)
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                               ENTRY_CALLS=str(calls), COLIMA_SSH_CONFIG=str(config),
                               ENTRY_FAIL_FIRST='yes' if fail_first else 'no')
            result = subprocess.run(['bash', str(REPO / 'mac-colima-saas.sh'), *arguments],
                                    env=environment, capture_output=True, text=True)
            observed = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, observed

    def test_async_entry_runs_both_real_cases_in_order_and_preserves_the_path(self):
        path = '/tmp/fixture generation'
        result, calls = self.entry(['verify-async-recovery', path])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([[str(REPO / 'scripts' / script), path] for script in (
            'verify-mac-demo-async-rpo.py', 'verify-mac-demo-async-reservation-loss.py')], calls)

    def test_failed_first_async_case_prevents_a_second_fault(self):
        result, calls = self.entry(['verify-async-recovery', '/tmp/fixture'], fail_first=True)
        self.assertEqual(23, result.returncode)
        self.assertEqual(1, len(calls))

    def test_native_entry_passes_exact_transport_and_load_parameters(self):
        arguments = ['/tmp/fixture generation', '--transport', 'tcp', '--rate', '15', '--seconds', '60']
        result, calls = self.entry(['verify-execution', *arguments])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([[str(REPO / 'scripts/verify-mac-demo-execution-capacity.py'), *arguments]], calls)

    def test_missing_generation_does_not_launch_a_case(self):
        for action in ('verify-execution', 'verify-async-recovery'):
            with self.subTest(action=action):
                result, calls = self.entry([action])
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], calls)


if __name__ == '__main__':
    unittest.main()
