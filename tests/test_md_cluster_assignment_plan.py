import copy
import unittest

from tests.md_cluster_assignment_plan import plan_primary_drain, stage_learner


ALLOWED = {"MDSvrA", "MDSvrB", "MDSvrC"}


def assignments():
    return [
        {
            "partitionId": "P000",
            "epoch": 7,
            "assignmentVersion": 10,
            "primary": "MDSvrA",
            "replica": "MDSvrB",
            "state": "READY",
        },
        {
            "partitionId": "P001",
            "epoch": 8,
            "assignmentVersion": 11,
            "primary": "MDSvrB",
            "replica": "MDSvrA",
            "state": "READY",
        },
    ]


class MdClusterAssignmentPlanTest(unittest.TestCase):
    def test_stage_learner_preserves_epoch_primary_and_input(self):
        source = assignments()
        before = copy.deepcopy(source)
        planned = stage_learner(source, 2, "MDSvrC", ALLOWED)

        self.assertEqual(before, source)
        self.assertEqual([7, 8], [row["epoch"] for row in planned])
        self.assertEqual(["MDSvrA", "MDSvrB"], [row["primary"] for row in planned])
        self.assertEqual([["MDSvrC"], ["MDSvrC"]], [row["learners"] for row in planned])
        self.assertEqual([11, 12], [row["assignmentVersion"] for row in planned])

    def test_drain_moves_only_source_primaries_through_recovering(self):
        staged = stage_learner(assignments(), 2, "MDSvrC", ALLOWED)
        recovering, ready = plan_primary_drain(
            staged, 2, "MDSvrA", "MDSvrC", ALLOWED
        )

        self.assertEqual(1, len(recovering))
        self.assertEqual("P000", recovering[0]["partitionId"])
        self.assertEqual("RECOVERING", recovering[0]["state"])
        self.assertEqual("READY", ready[0]["state"])
        self.assertEqual(8, recovering[0]["epoch"])
        self.assertEqual("MDSvrC", recovering[0]["primary"])
        self.assertEqual(["MDSvrB", "MDSvrA"], recovering[0]["replicas"])
        self.assertNotIn("MDSvrC", recovering[0]["learners"])
        self.assertEqual(12, recovering[0]["assignmentVersion"])
        self.assertEqual(13, ready[0]["assignmentVersion"])

    def test_drain_rejects_cold_target(self):
        with self.assertRaisesRegex(ValueError, "does not own hot state"):
            plan_primary_drain(assignments(), 2, "MDSvrA", "MDSvrC", ALLOWED)

    def test_stage_rejects_non_ready_input(self):
        source = assignments()
        source[0]["state"] = "RECOVERING"
        with self.assertRaisesRegex(ValueError, "not READY"):
            stage_learner(source, 2, "MDSvrC", ALLOWED)


if __name__ == "__main__":
    unittest.main()

