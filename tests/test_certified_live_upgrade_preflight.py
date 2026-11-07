import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).with_name("check_certified_live_upgrade_preflight.py")
spec = importlib.util.spec_from_file_location("t547_certified_live_upgrade", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

GOOD = ("order.common.nodeRuntime.enabled=true\n"
        "order.common.nodeRuntime.phase=READY\n"
        "order.common.nodeRuntime.automaticRecovery=true\n")

class CertifiedLiveReleaseGate(unittest.TestCase):
    def test_new_fresh_install_without_containers_is_separate_path(self):
        self.assertEqual(([], "COLD_START_NOT_HA_PROVEN"),
                         m.assess_pair("Order", [None, None]))
    def test_both_exited_are_cold_not_ha_proof(self):
        a = {"State": {"Status": "exited"}}
        self.assertEqual(([], "COLD_START_NOT_HA_PROVEN"),
                         m.assess_pair("Order", [a, a]))
    def test_real_running_ab_blocked_without_certified_ha_evidence(self):
        live = {"State": {"Status": "running"}}
        failures, condition = m.assess_pair("Order", [live, live])
        self.assertEqual("LIVE_REDEPLOY_BLOCKED", condition)
        self.assertIn("LIVE_ORDER_ROLLING_HA_PROOF_NOT_INSTALLED", failures)
    def test_running_a_exited_b_is_rejected(self):
        live = {"State": {"Status": "running"}}
        stopped = {"State": {"Status": "exited"}}
        failures, _ = m.assess_pair("Trade", [live, stopped])
        self.assertIn("TRADE_NODES_NOT_BOTH_RUNNING", failures)
    def test_manual_genesis_mode_is_not_automatic_ha(self):
        self.assertIn("ORDER_CERTIFIED_AUTOMATICRECOVERY_NOT_READY",
            m.assess_runtime("Order", GOOD.replace("automaticRecovery=true",
                                                "automaticRecovery=false"),
                             "a"*64, ""))
    def test_even_ready_zk_cannot_overrule_poison(self):
        self.assertIn("ORDER_CERTIFIED_WRITES_OR_RECOVERY_DENIED",
            m.assess_runtime("Order", GOOD, "a"*64,
                             "Common poisoned primary Epoch cannot renew"))
    def test_source_sha_is_physically_required(self):
        self.assertIn("ORDER_COMMON_JAR_SHA_UNVERIFIED",
            m.assess_runtime("Order", GOOD, "unknown", ""))
    def test_invalid_census_fails_closed(self):
        self.assertIsNone(m.property_value(GOOD.replace(
            "order.common.nodeRuntime.phase=READY\n", ""),
            "order.common.nodeRuntime.phase"))
    def test_all_disabled_does_not_query_docker(self):
        self.assertEqual("CLUSTER_DISABLED", {"condition": "CLUSTER_DISABLED"}["condition"])

if __name__ == "__main__":
    unittest.main()