import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


NATIVE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-native-tcp.py'))


class NativeTcpClientTest(unittest.TestCase):
    def work(self, identity):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        (work / 'identity.json').write_text(json.dumps(identity))
        return work

    def run_client(self, completed):
        identity = {'java_home': '/test-java', 'client_jvm_args': NATIVE['CLIENT_JVM_ARGS']}
        work = self.work(identity)
        completed.stderr = ''
        with patch.object(NATIVE['subprocess'], 'run', return_value=completed) as process:
            result = NATIVE['run'](work, {'seconds': 60, 'token': 'private-session'})
        arguments, options = process.call_args
        self.assertNotIn('private-session', ' '.join(arguments[0]))
        self.assertEqual('private-session', json.loads(options['input'])['token'])
        self.assertEqual(210, options['timeout'])
        self.assertEqual(NATIVE['CLIENT_JVM_ARGS'], arguments[0][1:1 + len(NATIVE['CLIENT_JVM_ARGS'])])
        return result

    def test_only_the_complete_native_report_is_accepted(self):
        result = self.run_client(SimpleNamespace(returncode=0, stdout='library output\nT554_NATIVE_TCP_REPORT {"orders": []}\n'))
        self.assertEqual([], result['orders'])
        self.assertTrue(Path(result['native_process_evidence']).is_file())

    def test_missing_or_ambiguous_reports_fail(self):
        for text in ['', 'T554_NATIVE_TCP_REPORT {}\nT554_NATIVE_TCP_REPORT {}\n']:
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, 'Native TCP client failed'):
                self.run_client(SimpleNamespace(returncode=0, stdout=text))

    def test_error_output_does_not_disclose_library_diagnostics(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_client(SimpleNamespace(returncode=2, stdout='private-session\nT554_NATIVE_TCP_FAILURE IOException\n'))
        self.assertNotIn('private-session', str(caught.exception))
        self.assertIn('IOException', str(caught.exception))

    def test_recorded_cancel_client_is_selected_without_exposing_credentials(self):
        work = self.work({'java_home': '/test-java', 'class_name': 'MacDemoNativeTcpOrderCancel',
                          'client_jvm_args': NATIVE['CLIENT_JVM_ARGS']})
        with patch.object(NATIVE['subprocess'], 'run', return_value=SimpleNamespace(
                    returncode=0, stdout='T554_NATIVE_TCP_REPORT {"orders": []}\n', stderr='')) as process:
            NATIVE['run'](work, {'seconds': 60, 'token': 'private-session'})
        self.assertEqual('MacDemoNativeTcpOrderCancel', process.call_args.args[0][-1])
        self.assertNotIn('private-session', repr(process.call_args.args))

    def test_an_unqualified_or_changed_memory_profile_cannot_run_silently(self):
        for profile in (None, ['-Xmx256m']):
            identity = {'java_home': '/test-java'}
            if profile is not None:
                identity['client_jvm_args'] = profile
            work = self.work(identity)
            with patch.object(NATIVE['subprocess'], 'run') as process:
                with self.assertRaisesRegex(RuntimeError, 'must pass preparation'):
                    NATIVE['run'](work, {'seconds': 60, 'token': 'private-session'})
            process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
