import unittest

from tests.md_cluster_roll_drain_host import ready_value, select_source_partitions


class MdClusterRollDrainHostTest(unittest.TestCase):
    def test_selects_sorted_bounded_source_primaries(self):
        rows = [
            {"partitionId": "P002", "primary": "MDSvrA"},
            {"partitionId": "P000", "primary": "MDSvrA"},
            {"partitionId": "P001", "primary": "MDSvrB"},
        ]
        self.assertEqual(["P000", "P002"], select_source_partitions(rows, "MDSvrA", 2))

    def test_ready_value_only_promotes_state_and_version(self):
        recovering = {
            "partitionId": "P132",
            "epoch": 2,
            "assignmentVersion": 2,
            "primary": "MDSvrC",
            "replicas": ["MDSvrB", "MDSvrA"],
            "learners": [],
            "state": "RECOVERING",
        }
        ready = ready_value(recovering)
        self.assertEqual("READY", ready["state"])
        self.assertEqual(3, ready["assignmentVersion"])
        self.assertEqual(2, ready["epoch"])
        self.assertEqual("RECOVERING", recovering["state"])


if __name__ == "__main__":
    unittest.main()
