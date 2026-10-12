import tempfile
import unittest
from pathlib import Path

from tests.trade_sync_replica_rolling_gate import evaluate, parse_required_flag


def assignment(p, primary="TradeSvrB", replicas=None):
    if replicas is None:
        replicas = ["TradeSvrA"]
    return {"partitionId": p, "primary": primary,
            "replicas": replicas, "replica": replicas[0],
            "state": "READY", "epoch": 7}


class TradeSyncReplicaRollingGateTest(unittest.TestCase):
    def test_stopping_single_required_replica_fails_closed(self):
        rows = [assignment("P023"), assignment("P054")]
        result = evaluate(rows, "TradeSvrA", True, False)
        self.assertEqual("BLOCK", result["status"])
        self.assertFalse(result["authorizesRollingRestart"])
        self.assertEqual({"ALL_REPLICA_ACKS_REQUIRED"},
                         {b["reason"] for b in result["blockingPartitions"]})

    def test_two_configured_replicas_still_all_ack_not_quorum(self):
        rows = [assignment("P023", replicas=["TradeSvrA", "TradeSvrC"])]
        result = evaluate(rows, "TradeSvrA", True, False)
        self.assertEqual("ALL_REPLICA_ACKS_REQUIRED",
                         result["blockingPartitions"][0]["reason"])

    def test_stopping_primary_always_blocked_without_verified_handoff(self):
        result = evaluate([assignment("P023")], "TradeSvrB", True, False)
        self.assertEqual("TARGET_IS_PRIMARY",
                         result["blockingPartitions"][0]["reason"])

    def test_partial_catalog_without_target_is_never_a_pass(self):
        result = evaluate([assignment("P023")], "TradeSvrC", True, False)
        self.assertEqual("UNPROVEN", result["status"])
        self.assertFalse(result["authorizesRollingRestart"])

    def test_legacy_assignment_and_complete_dormant_node(self):
        rows = [assignment("P%03d" % n) for n in range(256)]
        rows[0].pop("replicas")
        result = evaluate(rows, "TradeSvrC", True, True)
        self.assertTrue(result["authorizesRollingRestart"])
        self.assertEqual(256, result["checkedPartitions"])

    def test_bad_catalog_and_ambiguous_policy_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate([assignment("P023"), assignment("P023")], "TradeSvrA", True, False)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "application.properties"
            p.write_text("trade.cluster.replication.required=true\n")
            self.assertTrue(parse_required_flag(str(p)))
            p.write_text("trade.cluster.replication.required=true\n"
                         "trade.cluster.replication.required=false\n")
            with self.assertRaises(ValueError):
                parse_required_flag(str(p))


if __name__ == "__main__":
    unittest.main()
