import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native', Path(__file__).resolve().parents[1] / 'scripts/mac-demo-native-tcp.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'identity.json').write_text(json.dumps({
            'java_home': '/unused-jdk', 'client_jvm_args': native.CLIENT_JVM_ARGS}))
        self.config = {'seconds': 60, 'prefix': 'TEST', 'token': 'INPUT_SECRET_NOT_FOR_EVIDENCE'}

    def test_success_kept_before_caller_control_rejection(self):
        completed = SimpleNamespace(returncode=0, stdout='SDK_SESSION_PRIVATE\nT554_NATIVE_TCP_REPORT {"orders":[{"passed":true}]}\n', stderr='')
        with patch.object(native.subprocess, 'run', return_value=completed):
            result = native.run(self.root, self.config)
        proof = Path(result['native_process_evidence'])
        self.assertEqual(json.loads(proof.read_text())['returncode'], 0)
        self.assertEqual(json.loads(proof.read_text())['client_jvm_args'], native.CLIENT_JVM_ARGS)
        self.assertNotIn(self.config['token'], proof.read_text())
        self.assertIn('SDK_SESSION_PRIVATE', (proof.parent / 'stdout.txt').read_text())
        self.assertEqual(stat.S_IMODE(proof.parent.stat().st_mode), 0o700)
        for file in proof.parent.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        # The subsequent caller can fail without losing the original report.
        self.assertTrue(json.loads((proof.parent / 'stdout.txt').read_text().split('T554_NATIVE_TCP_REPORT ')[1])['orders'][0]['passed'])

    def test_failed_process_output_remains_private(self):
        completed = SimpleNamespace(returncode=2, stdout='SDK_SESSION_PRIVATE\nT554_NATIVE_TCP_FAILURE NATIVE_ACK_TIMEOUT\n', stderr='private stack')
        with patch.object(native.subprocess, 'run', return_value=completed), self.assertRaises(RuntimeError) as caught:
            native.run(self.root, self.config)
        self.assertNotIn('SDK_SESSION_PRIVATE', str(caught.exception))
        proof = Path(caught.exception.native_process_evidence)
        self.assertEqual(json.loads(proof.read_text())['returncode'], 2)
        self.assertEqual((proof.parent / 'stderr.txt').read_text(), 'private stack')

    def test_timeout_retains_partial_binary_output(self):
        expired = subprocess.TimeoutExpired(['java'], 210, output=b'partial report', stderr=b'partial error')
        with patch.object(native.subprocess, 'run', side_effect=expired), self.assertRaises(RuntimeError) as caught:
            native.run(self.root, self.config)
        proof = Path(caught.exception.native_process_evidence)
        self.assertTrue(json.loads(proof.read_text())['timed_out'])
        self.assertEqual((proof.parent / 'stdout.txt').read_bytes(), b'partial report')


if __name__ == '__main__':
    unittest.main()
