import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


NATIVE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-native-tcp.py'))


class NativeTcpClientTest(unittest.TestCase):
    def run_client(self, completed):
        identity = {'java_home': '/test-java'}
        work = Path('/test-native-client')
        with patch.object(Path, 'read_text', return_value=json.dumps(identity)), \
                patch.object(NATIVE['subprocess'], 'run', return_value=completed) as process:
            result = NATIVE['run'](work, {'seconds': 60, 'token': 'private-session'})
        arguments, options = process.call_args
        self.assertNotIn('private-session', ' '.join(arguments[0]))
        self.assertEqual('private-session', json.loads(options['input'])['token'])
        self.assertEqual(210, options['timeout'])
        return result

    def test_only_the_complete_native_report_is_accepted(self):
        result = self.run_client(SimpleNamespace(returncode=0, stdout='library output\nT554_NATIVE_TCP_REPORT {"orders": []}\n'))
        self.assertEqual({'orders': []}, result)

    def test_missing_or_ambiguous_reports_fail(self):
        for text in ['', 'T554_NATIVE_TCP_REPORT {}\nT554_NATIVE_TCP_REPORT {}\n']:
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, 'Native TCP client failed'):
                self.run_client(SimpleNamespace(returncode=0, stdout=text))

    def test_error_output_does_not_disclose_library_diagnostics(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_client(SimpleNamespace(returncode=2, stdout='private-session\nT554_NATIVE_TCP_FAILURE IOException\n'))
        self.assertNotIn('private-session', str(caught.exception))
        self.assertIn('IOException', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
