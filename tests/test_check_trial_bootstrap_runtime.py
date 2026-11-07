#!/usr/bin/env python3
"""Unit checks use fake credentials and guarantee no value appears in diagnoses."""
import importlib.util
import unittest
from pathlib import Path

p = Path(__file__).with_name("check-trial-bootstrap-runtime.py")
spec = importlib.util.spec_from_file_location("trial_runtime_preflight", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TrialRuntimePreflight(unittest.TestCase):
    def test_disabled_worker_not_mistaken_for_running(self):
        issues = mod.validate_admin_env(["TRIAL_LIQUIDITY_MASTER_KEY=" + "X" * 48])
        self.assertIn("ADMIN_BOOTSTRAP_DISABLED", issues)

    def test_valid_worker_has_independent_long_key_and_no_auto_retry(self):
        values = ["TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true",
                  "TRIAL_LIQUIDITY_MASTER_KEY=" + "X" * 48,
                  "TRIAL_LIQUIDITY_DEMO_RETRY_ENABLED=false",
                  "TRIAL_LIQUIDITY_TAPE_ENABLED=true"]
        self.assertEqual([], mod.validate_admin_env(values, require_tape=True))

    def test_missing_key_and_ambiguous_retry_are_no_go_without_secret_leakage(self):
        bad = ["TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true",
               "TRIAL_LIQUIDITY_MASTER_KEY=my-secret-value",
               "TRIAL_LIQUIDITY_DEMO_RETRY_ENABLED=true"]
        errs = mod.validate_admin_env(bad)
        self.assertIn("ADMIN_BOOTSTRAP_MASTER_KEY_ABSENT_OR_TOO_SHORT", errs)
        self.assertIn("ADMIN_UNSAFE_AMBIGUOUS_FUNDING_RETRY_ENABLED", errs)
        self.assertNotIn("my-secret-value", repr(errs))

    def test_robot_runtime_keys_are_required(self):
        env = ["ROBOT_GATEWAY_USER=fresh",
               "ROBOT_GATEWAY_PASSWORD=" + "P" * 48,
               "ROBOT_RUNTIME_USER_ID=robotsvr",
               "ROBOT_RUNTIME_LOCATION=PLATFORM",
               "ROBOT_RUNTIME_API_KEY=" + "K" * 48,
               "ROBOT_RUNTIME_API_SECRET=" + "S" * 48]
        self.assertEqual([], mod.validate_robot_env(env))
        self.assertIn("ROBOT_REQUIRED_ENV_MISSING:ROBOT_GATEWAY_USER",
                      mod.validate_robot_env(env[1:]))

    def test_inspect_rejects_unsafe_identifier_before_shell(self):
        with self.assertRaisesRegex(ValueError, "INVALID_CONTAINER_NAME"):
            mod.inspect_env("../privileged")


if __name__ == "__main__":
    unittest.main()