import importlib.util
import pathlib
import unittest


path = pathlib.Path(__file__).with_name("check_order_live_rollout_preflight.py")
spec = importlib.util.spec_from_file_location("rollout_preflight", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

GOOD = """order.common.nodeRuntime.enabled=true
order.common.nodeRuntime.phase=READY
order.common.nodeRuntime.automaticRecovery=true
"""
HASH = "a" * 64


class LiveOrderRolloutGuardTest(unittest.TestCase):
    def test_full_healthy_candidate_read_only_not_a_ha_proof(self):
        self.assertEqual([], m.assess_node({"State": {"Status": "running"}},
                                           GOOD, HASH, "active trading"))
    def test_manual_genesis_only_refuses_live_replacement(self):
        reasons = m.assess_node({"State": {"Status": "running"}},
                                GOOD.replace("automaticRecovery=true",
                                             "automaticRecovery=false"),
                                HASH, "")
        self.assertIn("AUTO_RECOVERY_DISABLED_NO_SAFE_ROLLING_REJOIN", reasons)
    def test_poisoned_primary_is_blocked_even_with_zk_ready(self):
        self.assertIn("PRIMARY_EPOCH_IRREVOCABLY_POISONED",
                      m.assess_node({"State": {"Status": "running"}}, GOOD,
                                    HASH, "Common poisoned primary Epoch cannot renew"))
    def test_sha_must_be_real_physical_hex(self):
        self.assertIn("COMMON_JAR_PHYSICAL_SHA_MISSING",
                      m.assess_node({"State": {"Status": "running"}}, GOOD,
                                    "not-a-sha", ""))
    def test_stopped_nodes_rejected(self):
        self.assertIn("NODE_NOT_RUNNING",
                      m.assess_node({"State": {"Status": "exited"}}, GOOD,
                                    HASH, ""))
    def test_any_error_robot_is_gate_failure(self):
        self.assertEqual(["ROBOT_NOT_RUNNING:ERROR:5"],
                         m.assess_robots([("RUNNING", 7), ("ERROR", 5)]))
    def test_no_running_workers_fail_closed(self):
        self.assertIn("NO_RUNNING_TRADING_ROBOTS",
                      m.assess_robots([("ERROR", 12)]))
    def test_missing_property_is_not_treated_as_enabled(self):
        self.assertIn("AUTO_RECOVERY_DISABLED_NO_SAFE_ROLLING_REJOIN",
                      m.assess_node({"State": {"Status": "running"}},
                                    "order.common.nodeRuntime.enabled=true\n"
                                    "order.common.nodeRuntime.phase=READY\n",
                                    HASH, ""))
    def test_business_denied_blocks_rollout(self):
        self.assertIn("CERTIFIED_PARTITION_WRITES_DENIED",
                      m.assess_node({"State": {"Status": "running"}}, GOOD,
                                    HASH, "ORDER_COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED"))


if __name__ == "__main__":
    unittest.main()