#!/usr/bin/env python3
"""T538 Robot gateway service-user bootstrap safety and one-click regression."""
import contextlib
import importlib.util
import io
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "robot_service_bootstrap", ROOT / "scripts" / "provision-robot-service-user.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RobotGatewayServiceUserTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "ROBOT_RUNTIME_USER_ID": "robotsvr",
            "ROBOT_RUNTIME_LOCATION": "PLATFORM",
            "ROBOT_RUNTIME_API_KEY": "A" * 32,
            "ROBOT_RUNTIME_API_SECRET": "B" * 32,
        }

    def test_identity_is_dedicated_platform_only(self):
        self.assertEqual(MODULE.identity(self.values)[:2], ("robotsvr", "PLATFORM"))
        with self.assertRaises(ValueError):
            MODULE.identity(dict(self.values, ROBOT_RUNTIME_LOCATION="TENANT"))
        with self.assertRaises(ValueError):
            MODULE.identity(dict(self.values, ROBOT_RUNTIME_USER_ID="robotsvr';DROP TABLE dc_users;--"))
        with self.assertRaises(ValueError):
            MODULE.identity(dict(self.values, ROBOT_RUNTIME_API_SECRET="A" * 32))

    def test_sql_creates_gateway_user_and_runtime_key_together(self):
        user, location, key, secret = MODULE.identity(self.values)
        sql = MODULE.sql_for(user, location, key, secret)
        self.assertIn("START TRANSACTION;", sql)
        self.assertIn("INSERT INTO dc_users(", sql)
        self.assertIn("INSERT INTO dc_users_api(", sql)
        self.assertIn("'ROBOT_RUNTIME'", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertIn("COMMIT;", sql)
        self.assertIn("SELECT 'ROBOT_API_COUNT'", sql)
        self.assertNotIn("PLATFORM_ADMIN_PASSWORD", sql)
        self.assertNotIn("TRUNCATE", sql)
        self.assertNotIn("DELETE FROM", sql)

    def test_read_env_only_reads_robot_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = pathlib.Path(tmp) / "private.env"
            env.write_text("\n".join([
                "ROBOT_RUNTIME_USER_ID=robotsvr",
                "ROBOT_RUNTIME_LOCATION=PLATFORM",
                "ROBOT_RUNTIME_API_KEY=" + "A" * 32,
                "ROBOT_RUNTIME_API_SECRET=" + "B" * 32,
                "MYSQL_ROOT_PASSWORD=DO_NOT_READ",
            ]), encoding="utf-8")
            self.assertEqual(MODULE.read_env(env), self.values)

    def test_mysql_credentials_do_not_go_into_host_argv_or_logs(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="ROBOT_USER_COUNT\t1\nROBOT_API_COUNT\t1\n",
                                           stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=fake) as run:
            out = MODULE.mysql_run("otc-test-mysql", "SELECT 1;")
        self.assertTrue(MODULE.counts(out))
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["docker", "exec", "-i", "otc-test-mysql"])
        self.assertNotIn("DO_NOT_READ", repr(argv))
        self.assertEqual(run.call_args.kwargs["input"], "SELECT 1;")
        self.assertNotIn("SQL", out)

    def test_main_prints_no_api_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "robot.env"
            path.write_text("\n".join("%s=%s" % item for item in self.values.items()),
                            encoding="utf-8")
            old = ["script", "--env-file", str(path), "--mysql-container", "otc-test-mysql"]
            output = io.StringIO()
            fake_counts = "ROBOT_USER_COUNT\t1\nROBOT_API_COUNT\t1\n"
            with mock.patch("sys.argv", old), mock.patch.object(
                    MODULE, "mysql_run", return_value=fake_counts), contextlib.redirect_stdout(output):
                MODULE.main()
            self.assertIn("changed=false", output.getvalue())
            self.assertNotIn("A" * 32, output.getvalue())
            self.assertNotIn("B" * 32, output.getvalue())

    def test_compose_and_one_click_share_dedicated_identity(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        deploy = (ROOT / "deploy-saas.sh").read_text(encoding="utf-8")
        self.assertIn("ROBOT_GATEWAY_USER: ${ROBOT_RUNTIME_USER_ID:-robotsvr}", compose)
        self.assertIn("ROBOT_GATEWAY_PASSWORD: ${ROBOT_RUNTIME_API_SECRET}", compose)
        self.assertIn("scripts/provision-robot-service-user.py", deploy)
        self.assertIn("provision_robot_runtime_identity", deploy)
        self.assertLess(deploy.index("provision_robot_runtime_identity\n",
                                     deploy.index("apply_mysql_migrations\n")),
                        deploy.index("compose_up -d\n", deploy.index("apply_mysql_migrations\n")))


if __name__ == "__main__":
    unittest.main()