import unittest

from tests.trade_cluster_assignments import build_initial_assignments, validate


class TradeClusterAssignmentsTest(unittest.TestCase):
    def test_builds_balanced_ab_topology(self):
        rows = build_initial_assignments(256)
        validate(rows, 256)

        self.assertEqual(256, len(rows))
        a = [row for row in rows if row["primary"] == "TradeSvrA"]
        b = [row for row in rows if row["primary"] == "TradeSvrB"]
        self.assertEqual(128, len(a))
        self.assertEqual(128, len(b))

        self.assertEqual("TradeSvrA", rows[0]["primary"])
        self.assertEqual("TradeSvrB", rows[0]["replica"])
        self.assertEqual("TradeSvrB", rows[128]["primary"])
        self.assertEqual("TradeSvrA", rows[128]["replica"])

    def test_every_assignment_is_protocol_v3_ready_epoch_one(self):
        rows = build_initial_assignments(8)
        validate(rows, 8)
        for row in rows:
            self.assertEqual(3, row["protocolVersion"])
            self.assertEqual(1, row["epoch"])
            self.assertEqual(1, row["assignmentVersion"])
            self.assertEqual("READY", row["state"])
            self.assertEqual([row["replica"]], row["replicas"])

    def test_rejects_same_primary_and_replica_node(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            build_initial_assignments(2, "TradeSvrA", "TradeSvrA")


if __name__ == "__main__":
    unittest.main()
