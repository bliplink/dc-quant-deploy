from pathlib import Path
import os
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUALIFY = runpy.run_path(str(ROOT / 'scripts/qualify-mac-common-candidate.py'))


class QualificationResultTest(unittest.TestCase):
    def parse(self, text, safety=False):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'result.log'
            log.write_text(text)
            return QUALIFY['checked_result'](log, safety)

    def test_actual_execution_is_separate_from_optional_skips(self):
        row = self.parse('COMMON_QUALIFICATION_RESULT discovered=317 executed=314 failures=0 '
                         'ignored=0 skipped=3 passed=true\n', True)
        self.assertEqual((314, 3), (row['executed'], row['optional_external_historical_skips']))
        with self.assertRaises(ValueError):
            self.parse('COMMON_QUALIFICATION_RESULT discovered=311 executed=308 failures=0 '
                       'ignored=0 skipped=3 passed=true\n', True)

    def test_empty_partial_ignored_failed_and_duplicate_results_are_not_passes(self):
        valid = 'COMMON_QUALIFICATION_RESULT discovered=1 executed=1 failures=0 ignored=0 skipped=0 passed=true\n'
        for bad in ('', valid * 2, valid.replace('executed=1', 'executed=0'),
                    valid.replace('ignored=0', 'ignored=1'), valid.replace('failures=0', 'failures=1'),
                    valid.replace('passed=true', 'passed=false'),
                    'COMMON_QUALIFICATION_RESULT discovered=1 executed=0 failures=0 ignored=0 skipped=1 passed=true\n'):
            with self.subTest(result=bad), self.assertRaises(ValueError):
                self.parse(bad)
        with self.assertRaises(ValueError):
            self.parse(valid, True)  # A tiny subset is not the mandatory safety suite.


class QualificationRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path('/usr/libexec/java_home').is_file():
            raise unittest.SkipTest('Mac Java 8 qualification runner')
        junit = Path.home() / '.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'
        hamcrest = Path.home() / '.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar'
        if not junit.is_file() or not hamcrest.is_file():
            raise unittest.SkipTest('Existing offline JUnit dependencies required')
        cls.java = Path(subprocess.check_output(['/usr/libexec/java_home', '-v', '1.8'], text=True).strip())
        cls.temporary = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temporary.name)
        cls.classpath = os.pathsep.join((str(cls.work), str(junit), str(hamcrest)))
        fixture = cls.work / 'QualificationFixture.java'
        fixture.write_text('''import org.junit.*;
public class QualificationFixture {
 @Test public void pass() {}
 @Test public void fail() { Assert.fail("fixture failure"); }
 @Test public void skip() { Assume.assumeTrue("unexpected skip", false); }
 @Ignore @Test public void ignored() {}
}''')
        subprocess.run([str(cls.java / 'bin/javac'), '-cp', cls.classpath, '-d', str(cls.work),
            str(ROOT / 'tests/fixtures/common-release/QualifiedCommonChecks.java'), str(fixture)],
            capture_output=True, text=True, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, *args):
        return subprocess.run([str(self.java / 'bin/java'), '-cp', self.classpath,
                               'QualifiedCommonChecks', *args], capture_output=True, text=True, timeout=15)

    def test_real_junit_failure_assumption_ignore_and_missing_method_fail_closed(self):
        good = self.invoke('--method', 'QualificationFixture', 'pass')
        self.assertEqual(0, good.returncode, good.stdout + good.stderr)
        for method in ('fail', 'skip', 'ignored', 'missing'):
            result = self.invoke('--method', 'QualificationFixture', method)
            with self.subTest(method=method):
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        result = self.invoke('--safety', 'QualificationFixture')
        self.assertEqual(2, result.returncode)


class QualificationEntryTest(unittest.TestCase):
    def test_one_click_builds_once_then_qualifies_and_stops_on_either_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            calls = directory / 'calls'
            (directory / 'uname').write_text('#!/bin/sh\necho Darwin\n')
            (directory / 'bash').write_text('''#!/bin/sh
case "$1" in
 */scripts/build-mac-common-candidate.sh) printf 'build %s %s\\n' "$2" "$3" >> "$COMMON_ENTRY_CALLS"; exit "${COMMON_BUILD_EXIT:-0}";;
 */mac-colima-saas.sh) test "$2" = fresh-verified || exit 92; printf 'fresh %s %s\\n' "$3" "$4" >> "$COMMON_ENTRY_CALLS"; exit "${COMMON_FRESH_EXIT:-0}";;
 *) exit 90;;
esac
''')
            (directory / 'python3').write_text('''#!/bin/sh
case "$1" in
 */scripts/qualify-mac-common-candidate.py) printf 'qualify %s %s\\n' "$2" "$3" >> "$COMMON_ENTRY_CALLS"; exit "${COMMON_QUALIFY_EXIT:-0}";;
 *) exit 91;;
esac
''')
            for name in ('uname', 'bash', 'python3'):
                (directory / name).chmod(0o700)
            for build, qualify, expected, count in ((0, 0, 0, 2), (7, 0, 7, 1), (0, 8, 8, 2)):
                calls.write_text('')
                result = subprocess.run(['/bin/bash', str(ROOT / 'mac-colima-saas.sh'),
                                         'verify-common', 'reviewed-revision'], capture_output=True, text=True,
                    env=dict(os.environ, PATH=str(directory) + ':' + os.environ['PATH'],
                             COLIMA_SSH_CONFIG='/dev/null', COMMON_ENTRY_CALLS=str(calls),
                             COMMON_BUILD_EXIT=str(build), COMMON_QUALIFY_EXIT=str(qualify)))
                self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
                rows = calls.read_text().splitlines()
                self.assertEqual(count, len(rows))
                self.assertEqual('reviewed-revision', rows[0].split()[1])
                if count == 2:
                    self.assertEqual(rows[0].split()[2], rows[1].split()[1])

            # A failing physical/safety gate must never reach deployment.
            # A deployment failure must also remain a failed one-click run.
            for build, qualify, fresh, expected, count in (
                    (0, 0, 0, 0, 3), (7, 0, 0, 7, 1), (0, 8, 0, 8, 2), (0, 0, 9, 9, 3)):
                calls.write_text('')
                result = subprocess.run(['/bin/bash', str(ROOT / 'mac-colima-saas.sh'),
                                         'verify-and-fresh', 'reviewed-revision'], capture_output=True, text=True,
                    env=dict(os.environ, PATH=str(directory) + ':' + os.environ['PATH'],
                             COLIMA_SSH_CONFIG='/dev/null', COMMON_ENTRY_CALLS=str(calls),
                             COMMON_BUILD_EXIT=str(build), COMMON_QUALIFY_EXIT=str(qualify),
                             COMMON_FRESH_EXIT=str(fresh)))
                self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
                rows = calls.read_text().splitlines()
                self.assertEqual(count, len(rows))
                if count == 3:
                    self.assertEqual(rows[0].split()[2], rows[2].split()[1])
                    self.assertEqual(rows[1].split()[1:], rows[2].split()[1:])


if __name__ == '__main__':
    unittest.main()
