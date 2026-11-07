#!/usr/bin/env python3
"""Pure contract tests for the read-only trial Robot live gate."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "trial_robot_check", ROOT / "check_trial_robot_live_readiness.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture():
    secret = "TEST_ONLY_32_CHARACTERS_SENTINEL_1"
    admin = {"running": True, "env": {
        "TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED": "true",
        "TRIAL_LIQUIDITY_MASTER_KEY": "TEST_ONLY_MASTER_KEY",
        "TRIAL_LIQUIDITY_GATEWAY_URL": "http://127.0.0.1:43002/httpapi/",
    }}
    robot = {"running": True, "env": {
        "ROBOT_GATEWAY_USER": "robotsvr", "ROBOT_RUNTIME_USER_ID": "robotsvr",
        "ROBOT_GATEWAY_PASSWORD": secret,
        "ROBOT_RUNTIME_API_SECRET": secret,
        "ROBOT_RUNTIME_API_KEY": "TEST_ONLY_API_KEY",
        "GATEWAY_HTTP_URL": "http://127.0.0.1:43002/api",
    }}
    aps = {"running": True}
    stats = {"bootstrap_total": 6, "bootstrap_complete": 6,
             "robot_enabled": 6, "robot_live": 6, "robot_stale": 0}
    return admin, robot, aps, stats


class RobotLiveReadinessTests(unittest.TestCase):
    def test_complete_contract_only_preflight(self):
        a, r, p, s = fixture()
        self.assertEqual(M.assess(a, r, p, s, True, False), [])

    def test_worker_disabled_or_missing_master_key(self):
        a, r, p, s = fixture()
        a["env"]["TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED"] = "false"
        a["env"].pop("TRIAL_LIQUIDITY_MASTER_KEY")
        result = M.assess(a, r, p, s, True, False)
        self.assertIn("TRIAL_WORKER_NOT_RUNNING", result)
        self.assertIn("TRIAL_BOOTSTRAP_MASTER_KEY_MISSING", result)

    def test_gateway_identity_must_match_runtime_api(self):
        a, r, p, s = fixture()
        r["env"]["ROBOT_GATEWAY_USER"] = "platformadmin"
        r["env"]["ROBOT_GATEWAY_PASSWORD"] = "unrelated"
        result = M.assess(a, r, p, s, True, False)
        self.assertIn("ROBOT_GATEWAY_USER_MISMATCH", result)
        self.assertIn("ROBOT_GATEWAY_CREDENTIALS_MISSING_OR_MISMATCH", result)

    def test_wrong_gateway_port_rejected(self):
        a, r, p, s = fixture()
        a["env"]["TRIAL_LIQUIDITY_GATEWAY_URL"] = "http://127.0.0.1:33002/httpapi/"
        self.assertIn("TRIAL_GATEWAY_PORT_MISMATCH", M.assess(a, r, p, s, True, False))

    def test_unavailable_binance_and_empty_book_rejected(self):
        a, r, p, s = fixture()
        s["robot_live"] = 0
        s["robot_stale"] = 6
        result = M.assess(a, r, p, s, True, True)
        self.assertIn("BINANCE_DNS_UNAVAILABLE", result)
        self.assertIn("NO_LIVE_TWO_SIDED_QUOTES", result)

    def test_missing_worker_source_and_robot_tasks(self):
        a, r, p, s = fixture()
        p["running"] = False
        s["bootstrap_total"] = 0
        s["robot_enabled"] = 0
        self.assertIn("BINANCE_SOURCE_DISABLED_OR_NOT_RUNNING",
                      M.assess(a, r, p, s, False, False))
        self.assertIn("NO_TRIAL_BOOTSTRAP_JOBS",
                      M.assess(a, r, p, s, False, False))
        self.assertIn("NO_ENABLED_ROBOT_TASKS",
                      M.assess(a, r, p, s, False, False))


if __name__ == "__main__":
    unittest.main()