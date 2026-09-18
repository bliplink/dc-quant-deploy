import unittest

from tests.trade_cluster_transition_host import parse_ready_evidence, switch_assignment


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


if __name__ == "__main__":
    unittest.main()
