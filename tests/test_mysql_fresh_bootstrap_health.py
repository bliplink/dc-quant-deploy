"""Verify fail-closed cold MySQL init even after a partial-schema restart."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "mysql/init/check-schema-ready.sh"


class ColdMysqlSchemaReadyTest(unittest.TestCase):
    def test_bootstrap_scripts_install_marker_before_all_versioned_migrations(self):
        start = (ROOT / "mysql/init/01-schema-initializing.sql").read_text()
        finish = (ROOT / "mysql/init/20-apply-migrations.sh").read_text()
        self.assertIn("VALUES ('all-migrations-done',0)", start)
        self.assertIn("VALUES ('all-migrations-done',1)", finish)
        self.assertLess(Path('01-schema-initializing.sql').name,
                        Path('20-apply-migrations.sh').name)

    def test_health_denies_incomplete_init_but_preserves_legacy_upgrade(self):
        with tempfile.TemporaryDirectory() as path:
            mock = Path(path) / 'mysql'
            mock.write_text('''#!/bin/sh
case "$*" in
  *"SELECT ready FROM"*) echo "$MOCK_READY" ;;
  *"dc_fresh_schema_install_status"*) echo "$MOCK_MARKER" ;;
  *"dc_tenant"*) echo "$MOCK_TABLES" ;;
  *) exit 1 ;;
esac
''')
            mock.chmod(0o755)
            for marker, ready, tables, expected in (
                ('1', '0', '4', 1),  # MySQL rebooted after failed DDL
                ('1', '1', '4', 0),  # all migrations completed
                ('1', '1', '3', 1),  # mandatory business table missing
                ('0', '0', '4', 0),  # older in-place install, no marker table
                ('0', '0', '3', 1),
            ):
                with self.subTest(marker=marker, ready=ready, tables=tables):
                    env = os.environ.copy()
                    env.update(PATH=path + os.pathsep + env['PATH'],
                               MYSQL_ROOT_PASSWORD='test-only',
                               MOCK_MARKER=marker, MOCK_READY=ready,
                               MOCK_TABLES=tables)
                    proc = subprocess.run(['sh', str(CHECK)], env=env,
                                          capture_output=True, text=True,
                                          timeout=8)
                    self.assertEqual(proc.returncode == 0, expected == 0,
                                     (proc.stdout, proc.stderr))


if __name__ == '__main__':
    unittest.main()
