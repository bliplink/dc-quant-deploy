"""Deterministic fail-closed Order HA rollout gate regressions; no Docker required."""
import unittest

from tests.order_ha_rollout_gate import issues_for_snapshot


def healthy():
    return {
        "resources": {
            "cpu_some_avg60": 5.0,
            "mem_available_kib": 4 * 1024 * 1024,
            "swap_free_kib": 512 * 1024,
        },
        "nodes": {
            name: {"running": True, "oom": False, "restarts": 0}
            for name in ("OrderSvrA", "OrderSvrB", "OrderSvrC")
        },
        "robots": {"running": 50, "other": 0, "open_order_count": 2000},
        # Target A is a learner only; the durable B->C replication remains.
        "partitions": [
            {"partitionId": "P%03d" % i, "state": "READY", "epoch": 1,
             "primary": "OrderSvrB", "replicas": ["OrderSvrC"],
             "learners": ["OrderSvrA"]}
            for i in range(256)
        ],
    }


class OrderHaRolloutGateTest(unittest.TestCase):
    def test_healthy_idle_learner_passes_read_only_preflight(self):
        self.assertEqual([], issues_for_snapshot(healthy(), "OrderSvrA"))

    def test_cpu_pressure_blocks_even_if_robots_look_healthy(self):
        state = healthy()
        state["resources"]["cpu_some_avg60"] = 75.0
        self.assertTrue(any("CPU pressure" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))

    def test_low_memory_and_swap_block(self):
        state = healthy()
        state["resources"]["mem_available_kib"] = 100000
        state["resources"]["swap_free_kib"] = 25
        problems = issues_for_snapshot(state, "OrderSvrA")
        self.assertTrue(any("MemAvailable" in s for s in problems))
        self.assertTrue(any("SwapFree" in s for s in problems))

    def test_robot_degraded_blocks(self):
        state = healthy()
        state["robots"]["running"] = 49
        state["robots"]["other"] = 1
        self.assertTrue(any("Robot not stable" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))

    def test_primary_owner_must_be_drained(self):
        state = healthy()
        state["partitions"][0]["primary"] = "OrderSvrA"
        state["partitions"][0]["replicas"] = ["OrderSvrC"]
        self.assertTrue(any("owns 1 primary" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))

    def test_synchronous_replica_must_be_safely_reconfigured(self):
        state = healthy()
        state["partitions"][0]["replicas"] = ["OrderSvrA"]
        self.assertTrue(any("1 synchronous replica" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))

    def test_topology_missing_or_not_ready_blocks(self):
        state = healthy()
        state["partitions"].pop()
        self.assertTrue(any("256 complete" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))
        state = healthy()
        state["partitions"][10]["state"] = "RECOVERING"
        self.assertTrue(any("not READY" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))

    def test_duplicate_partition_blocks(self):
        state = healthy()
        state["partitions"][1]["partitionId"] = "P000"
        self.assertTrue(any("duplicate" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))

    def test_missing_evidence_is_not_success(self):
        self.assertTrue(issues_for_snapshot({}, "OrderSvrA"))
        state = healthy()
        del state["nodes"]["OrderSvrC"]
        self.assertTrue(any("incomplete" in s for s in
                            issues_for_snapshot(state, "OrderSvrA")))


if __name__ == "__main__":
    unittest.main()
