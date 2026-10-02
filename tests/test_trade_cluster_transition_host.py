import json
import tempfile
import unittest
from types import SimpleNamespace

from tests.trade_cluster_transition_host import command_verify, parse_ready_evidence, switch_assignment


class TradeClusterTransitionHostTest(unittest.TestCase):
    def current(self):
        return {
            "partitionId": "P027",
            "epoch": 7,
            "assignmentVersion": 11,
            "protocolVersion": 3,
            "primary": "TradeSvrA",
            "replica": "TradeSvrB",
            "replicas": ["TradeSvrB"],
            "learners": [],
            "placementGroup": "",
            "nodePool": "trade-ab",
            "state": "READY",
        }

    def test_switch_advances_epoch_and_swaps_primary_replica(self):
        desired = switch_assignment(self.current(), "TradeSvrA", "TradeSvrB")
        self.assertEqual(8, desired["epoch"])
        self.assertEqual(12, desired["assignmentVersion"])
        self.assertEqual("TradeSvrB", desired["primary"])
        self.assertEqual("TradeSvrA", desired["replica"])
        self.assertEqual(["TradeSvrA"], desired["replicas"])
        self.assertEqual("READY", desired["state"])

    def test_switch_rejects_non_replica_target(self):
        row = self.current()
        row["replica"] = "TradeSvrA"
        row["replicas"] = ["TradeSvrA"]
        with self.assertRaises(ValueError):
            switch_assignment(row, "TradeSvrA", "TradeSvrB")

    def test_ready_evidence_is_partition_epoch_specific(self):
        text = (
            "TRADE_PARTITION_READY node:TradeSvrB, partition:P027, epoch:8, "
            "committedStateSeq:123, locations:4\n"
        )
        self.assertEqual({("TradeSvrB", "P027", 8)}, parse_ready_evidence(text))

    def test_verify_waits_for_ready_evidence_before_passing(self):
        desired = switch_assignment(self.current(), "TradeSvrA", "TradeSvrB")
        plan = {
            "schemaVersion": 1,
            "operation": "trade-primary-switch",
            "createdAt": "2026-10-02T00:00:00Z",
            "partitionRoot": "/dc/cluster/tradesvr/partitions",
            "source": "TradeSvrA",
            "target": "TradeSvrB",
            "records": [{"partitionId": "P027", "desired": desired}],
        }

        class FakeZk:
            def __init__(self):
                self.log_calls = 0

            def read(self, partition_id):
                self.assert_partition = partition_id
                return {"value": desired}

            def logs(self, container, since):
                self.log_calls += 1
                if self.log_calls == 1:
                    return ""
                return (
                    "TRADE_PARTITION_READY node:TradeSvrB, partition:P027, epoch:8, "
                    "committedStateSeq:0, locations:0\n"
                )

        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(plan, handle)
            handle.flush()
            args = SimpleNamespace(
                plan=handle.name,
                partition_root=plan["partitionRoot"],
                target_node="TradeSvrB",
                target_container="trade-b",
                timeout_seconds=1.0,
                poll_seconds=0.001,
            )
            zk = FakeZk()
            command_verify(args, zk)
            self.assertGreaterEqual(zk.log_calls, 2)


if __name__ == "__main__":
    unittest.main()