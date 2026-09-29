import unittest

from tests.migrate_trade_cluster_assignments_host import migrate_assignment


class TradeAssignmentMigrationTest(unittest.TestCase):
    def legacy(self):
        return {
            "partitionId": "P209",
            "epoch": 7,
            "primary": "TradeSvrB",
            "replica": "TradeSvrA",
            "state": "READY",
        }

    def test_legacy_shape_is_enriched_without_topology_change(self):
        current = self.legacy()
        desired = migrate_assignment(current)
        self.assertEqual("P209", desired["partitionId"])
        self.assertEqual(7, desired["epoch"])
        self.assertEqual("TradeSvrB", desired["primary"])
        self.assertEqual("TradeSvrA", desired["replica"])
        self.assertEqual(["TradeSvrA"], desired["replicas"])
        self.assertEqual("READY", desired["state"])
        self.assertEqual(1, desired["assignmentVersion"])
        self.assertEqual(3, desired["protocolVersion"])

    def test_existing_versions_are_preserved(self):
        current = self.legacy()
        current.update({"assignmentVersion": 9, "protocolVersion": 4, "replicas": ["TradeSvrA"]})
        desired = migrate_assignment(current)
        self.assertEqual(9, desired["assignmentVersion"])
        self.assertEqual(4, desired["protocolVersion"])

    def test_overlapping_primary_replica_is_rejected(self):
        current = self.legacy()
        current["replica"] = "TradeSvrB"
        with self.assertRaises(ValueError):
            migrate_assignment(current)


if __name__ == "__main__":
    unittest.main()
