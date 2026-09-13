import unittest

from tests.md_cluster_transition_host import (
    parse_ready_evidence,
    parse_zk_get,
    partition_for_route,
    require_route_evidence,
    validate_transition,
)


class MdClusterTransitionHostTest(unittest.TestCase):
    def test_parse_zk_get_requires_payload_and_data_version(self):
        output = """
{"partitionId":"P027","epoch":7,"primary":"MDSvrA","replica":"MDSvrB","state":"READY"}
cZxid = 0x1
dataVersion = 12
numChildren = 0
"""
        value, version = parse_zk_get(output, "P027")
        self.assertEqual("MDSvrA", value["primary"])
        self.assertEqual(12, version)

    def test_route_hash_matches_java_partition_contract(self):
        self.assertEqual(
            "P027",
            partition_for_route(
                {"location": "WEB_E2E", "marketIndicator": "4", "securityID": "BTCUSDT"},
                256,
            ),
        )

    def test_learner_transition_cannot_change_epoch_or_primary(self):
        current = assignment()
        desired = {**current, "assignmentVersion": 11, "learners": ["MDSvrC"]}
        validate_transition(current, desired, "stage-learner", learner="MDSvrC")
        desired["epoch"] = 8
        with self.assertRaisesRegex(ValueError, "changed epoch"):
            validate_transition(current, desired, "stage-learner", learner="MDSvrC")

    def test_drain_requires_hot_target_and_one_epoch(self):
        current = assignment()
        current["learners"] = ["MDSvrC"]
        desired = {
            **current,
            "epoch": 8,
            "assignmentVersion": 11,
            "primary": "MDSvrC",
            "replica": "MDSvrB",
            "replicas": ["MDSvrB", "MDSvrA"],
            "learners": [],
            "state": "RECOVERING",
        }
        validate_transition(
            current, desired, "drain-recovering", source="MDSvrA", target="MDSvrC"
        )
        desired["epoch"] = 9
        with self.assertRaisesRegex(ValueError, "epoch"):
            validate_transition(
                current, desired, "drain-recovering", source="MDSvrA", target="MDSvrC"
            )

    def test_ready_evidence_is_route_exact(self):
        text = (
            "MD_MARKET_READY node:MDSvrC, partition:P027, epoch:7, role:LEARNER, "
            "location:WEB_E2E, market:4, securityId:BTCUSDT\n"
        )
        evidence = parse_ready_evidence(text)
        routes = [{"location": "WEB_E2E", "marketIndicator": "4", "securityID": "BTCUSDT"}]
        require_route_evidence(
            routes, {"P027": assignment()}, "MDSvrC", "LEARNER", evidence, 256
        )
        with self.assertRaisesRegex(RuntimeError, "missing MD_MARKET_READY"):
            require_route_evidence(
                routes, {"P027": assignment()}, "MDSvrC", "PRIMARY", evidence, 256
            )


def assignment():
    return {
        "partitionId": "P027",
        "epoch": 7,
        "assignmentVersion": 10,
        "primary": "MDSvrA",
        "replica": "MDSvrB",
        "state": "READY",
    }


if __name__ == "__main__":
    unittest.main()
