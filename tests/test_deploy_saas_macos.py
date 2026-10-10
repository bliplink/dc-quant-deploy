"""Mock Docker/macOS to test one-click wrapper without touching live Docker."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MacOneClickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'bin').mkdir()
        (self.root / 'release').mkdir()
        (self.root / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'deploy-saas-macos.sh', self.root / 'deploy-saas-macos.sh')
        (self.root / 'deploy-saas-macos.sh').chmod(0o755)
        (self.root / 'compose.yaml').write_text('services: {}\n')
        (self.root / 'release/saas-crypto-images.env').write_text('ORDERSVR_TAG=sha-7842df4\n')
        (self.root / '.env.prod').write_text('IMAGE_SOURCE=registry\nSECRET_DO_NOT_PRINT=example\n')
        self.deployed = self.root / 'child-run.txt'
        self.lock = self.root / 'install.lock.macos'
        self.env = dict(os.environ)
        self.env.update({
            'PATH': str(self.root / 'bin') + os.pathsep + os.environ['PATH'],
            'HOME': str(self.root),
            'ENV_FILE': str(self.root / '.env.prod'),
            'MACOS_DEPLOY_ROOT': str(self.root / 'runtime'),
            'MACOS_BUILD_ROOT': str(self.root / 'build'),
            'SAAS_AUTO_UPDATE_LOCK_FILE': str(self.root / 'install.lock'),
            'TEST_CHILD_OUT': str(self.deployed),
        })
        self.make_bin('uname', '#!/bin/sh\necho Darwin\n')
        self.make_bin('sysctl', '#!/bin/sh\necho 17179869184\n')
        self.make_bin('docker', '''#!/bin/sh
case "$1" in
  info) test "${FAKE_DOCKER_DOWN:-0}" != 1 ;;
  context) echo colima ;;
  compose)
    if [ "$2" = version ]; then exit 0; fi
    [ "${FAKE_COMPOSE_INVALID:-0}" != 1 ] || exit 8
    if [ -n "${TEST_COMPOSE_PROFILES_LOG:-}" ]; then
      printf '%s\\n' "${COMPOSE_PROFILES:-none}" >> "$TEST_COMPOSE_PROFILES_LOG"
    fi
    exit 0 ;;
  ps) echo 'dc-saas-ordersvr' ;;
  *) exit 77 ;;
esac
''')
        (self.root / 'scripts/apply-release-image-lock.sh').write_text(
            '#!/bin/sh\necho "LOCK_APPLIED=yes" >> "$1"\n')
        (self.root / 'scripts/upsert-env-value.sh').write_text(
            '#!/bin/sh\necho "$2=$3" >> "$1"\n')
        for name in ('apply-release-image-lock.sh', 'upsert-env-value.sh'):
            (self.root / 'scripts' / name).chmod(0o755)
        (self.root / 'deploy-saas.sh').write_text('''#!/bin/sh
printf 'HELD=%s HOST=%s PREFLIGHT=%s\\n' "${SAAS_DEPLOY_LOCK_HELD:-}" "${SAAS_ALLOW_UNPRIVILEGED_HOST:-}" "${SAAS_SKIP_LINUX_HOST_PREFLIGHT:-}" > "$TEST_CHILD_OUT"
exit "${FAKE_CHILD_EXIT:-0}"
''')
        (self.root / 'deploy-saas.sh').chmod(0o755)

    def make_bin(self, name, body):
        p = self.root / 'bin' / name
        p.write_text(body)
        p.chmod(0o755)

    def run_wrapper(self, *args, updates=None):
        env = dict(self.env)
        env.update(updates or {})
        return subprocess.run([str(self.root / 'deploy-saas-macos.sh'), *args],
                              env=env, text=True, capture_output=True, timeout=15)

    def test_reset_routes_to_fenced_mac_script_not_install(self):
        helper=self.root/'scripts/mac-saas-reset.py'
        helper.write_text("""import sys
print("COLD_RESET_ROUTED", " ".join(sys.argv[1:]))
""")
        result=self.run_wrapper('reset','--help')
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertIn('COLD_RESET_ROUTED --help',result.stdout)
        self.assertFalse(self.deployed.exists())

    def test_check_is_read_only_with_realistic_existing_containers(self):
        before = (self.root / '.env.prod').read_bytes()
        result = self.run_wrapper('--check')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, (self.root / '.env.prod').read_bytes())
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.deployed.exists())
        self.assertFalse((self.root / 'runtime').exists())
        self.assertIn('Docker context=colima', result.stdout)

    def test_full_cluster_check_selects_all_profiles(self):
        log = self.root / 'profiles.txt'
        result = self.run_wrapper('--check', '--full-cluster',
                                  updates={'TEST_COMPOSE_PROFILES_LOG':str(log)})
        self.assertEqual(0, result.returncode, result.stderr)
        value = log.read_text()
        self.assertIn('order-cluster-c', value)
        self.assertIn('md-cluster-c', value)
        self.assertIn('trade-cluster', value)

    def test_check_rejects_unknown_arguments(self):
        result = self.run_wrapper('--check', '--purge-data')
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.deployed.exists())

    def test_preexisting_lock_prevents_any_env_mutation(self):
        self.lock.mkdir()
        before = (self.root / '.env.prod').read_bytes()
        result = self.run_wrapper('--full-cluster')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, (self.root / '.env.prod').read_bytes())
        self.assertTrue(self.lock.exists())
        self.assertFalse(self.deployed.exists())

    def test_install_passes_privilege_flags_and_releases_lock(self):
        result = self.run_wrapper('--full-cluster')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('HELD=true HOST=true PREFLIGHT=true', self.deployed.read_text().strip())
        self.assertFalse(self.lock.exists())
        self.assertIn('LOCK_APPLIED=yes', (self.root / '.env.prod').read_text())
        self.assertTrue((self.root / 'runtime').is_dir())

    def test_failed_child_releases_lock_and_propagates_exit(self):
        result = self.run_wrapper('--full-cluster', updates={'FAKE_CHILD_EXIT':'37'})
        self.assertEqual(37, result.returncode, result.stderr)
        self.assertFalse(self.lock.exists())

    def test_unavailable_docker_blocks_any_writes(self):
        original = (self.root / '.env.prod').read_bytes()
        result = self.run_wrapper('--full-cluster', updates={'FAKE_DOCKER_DOWN':'1'})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(original, (self.root / '.env.prod').read_bytes())
        self.assertFalse(self.lock.exists())

    def test_invalid_full_cluster_compose_blocks_check(self):
        result = self.run_wrapper('--check','--full-cluster',
                                  updates={'FAKE_COMPOSE_INVALID':'1'})
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.deployed.exists())

if __name__ == '__main__':
    unittest.main()
