import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / 'mac-colima-saas.sh'


class AsyncRecoveryEntryTest(unittest.TestCase):
    def test_tools_precede_faults_and_each_failure_stops_the_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = root / 'mac-demo-20261115-180803'
            generation.mkdir()
            for name, text in {
                'uname': '#!/bin/bash\nprintf "Darwin\\n"\n',
                'docker': '#!/bin/bash\nprintf "sha256:existing-test-image\\n"\n',
                'python3': ('#!/bin/bash\nprintf "%s\\n" "$*" >> "$MAC_RPO_TEST_CALLS"\n'
                            '[[ "$(basename "$1")" != "$MAC_RPO_TEST_FAIL" ]]\n'),
            }.items():
                p = root / name
                p.write_text(text)
                p.chmod(0o700)
            names = ['build-mac-demo-rpo-fault-tools.py', 'verify-mac-demo-async-rpo.py',
                     'verify-mac-demo-async-reservation-loss.py', 'verify-mac-demo-async-reservation-loss.py']
            for failed in ('', *dict.fromkeys(names)):
                with self.subTest(failed=failed):
                    calls = root / 'calls'
                    calls.write_text('')
                    env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                               COLIMA_SSH_CONFIG='/dev/null', MAC_RPO_TEST_CALLS=str(calls),
                               MAC_RPO_TEST_FAIL=failed)
                    result = subprocess.run(['/bin/bash', str(ENTRY), 'verify-async-recovery', str(generation)],
                                            env=env, capture_output=True, text=True)
                    rows = calls.read_text().splitlines()
                    expected = names if not failed else names[:names.index(failed) + 1]
                    self.assertEqual(expected, [Path(row.split()[0]).name for row in rows])
                    self.assertEqual(not failed, result.returncode == 0)
                    if len(rows) > 1:
                        tools = rows[0].split()[1]
                        self.assertTrue(tools.startswith(str(generation / 'async-recovery-tools-')))
                        for index, row in enumerate(rows[1:], 1):
                            suffix = ' --after-loss match' if index == 3 else ''
                            self.assertTrue(row.endswith('--tools ' + tools + suffix))


if __name__ == '__main__':
    unittest.main()
