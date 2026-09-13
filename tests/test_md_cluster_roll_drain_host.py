import unittest

from tests.md_cluster_roll_drain_host import parser, ready_value, select_source_partitions


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

    def test_replica_target_readiness_role_is_supported(self):
        args = parser().parse_args(
            [
                "--source", "MDSvrB",
                "--target", "MDSvrA",
                "--active-routes", "active.jsonl",
                "--target-container", "dc-saas-mdsvr",
                "--target-ready-since", "2026-09-13T13:28:57Z",
                "--target-ready-role", "REPLICA",
                "--evidence-dir", "evidence",
                "--confirm-root", "/dc/cluster/mdsvr/partitions",
            ]
        )
        self.assertEqual("REPLICA", args.target_ready_role)
        self.assertEqual("2026-09-13T13:28:57Z", args.target_ready_since)

    def test_learner_since_alias_remains_compatible(self):
        args = parser().parse_args(
            [
                "--source", "MDSvrA",
                "--target", "MDSvrC",
                "--active-routes", "active.jsonl",
                "--target-container", "dc-saas-mdsvr-c",
                "--learner-since", "2026-09-13T12:38:42Z",
                "--evidence-dir", "evidence",
                "--confirm-root", "/dc/cluster/mdsvr/partitions",
            ]
        )
        self.assertEqual("LEARNER", args.target_ready_role)
        self.assertEqual("2026-09-13T12:38:42Z", args.target_ready_since)


if __name__ == "__main__":
    unittest.main()
