import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import json
from pathlib import Path

from tests.md_cluster_transition_host import (
    apply_records,
    command_stage,
    parse_ready_evidence,
    parse_zk_get,
    parse_zk_get_many,
    parser,
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

    def test_parse_many_pairs_each_payload_with_its_stat(self):
        output = """
{"partitionId":"P000","epoch":7}
dataVersion = 2
numChildren = 0
{"partitionId":"P001","epoch":8}
dataVersion = 3
numChildren = 0
"""
        result = parse_zk_get_many(output, ["P000", "P001"])
        self.assertEqual(2, result["P000"][1])
        self.assertEqual(8, result["P001"][0]["epoch"])

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

    def test_apply_records_uses_bounded_cas_batches(self):
        class FakeZk:
            def __init__(self):
                self.sizes = []

            def cas_many(self, records):
                self.sizes.append(len(records))

        records = []
        for index in range(5):
            current = assignment()
            current["partitionId"] = f"P{index:03d}"
            desired = {**current, "assignmentVersion": 11, "learners": ["MDSvrC"]}
            records.append({"partitionId": current["partitionId"], "value": current, "desired": desired})
        zk = FakeZk()
        apply_records(zk, records, "stage-learner", 2, learner="MDSvrC")
        self.assertEqual([2, 2, 1], zk.sizes)

    def test_manual_md_drain_and_promote_never_write_without_durable_source_proof(self):
        class PoisonZk:
            def cas_many(self, *args):
                raise AssertionError("unsafe primary transition reached ZooKeeper")
        current = assignment()
        current["learners"] = ["MDSvrC"]
        draining = {**current, "epoch": 8, "assignmentVersion": 11,
                    "primary": "MDSvrC", "replica": "MDSvrB",
                    "replicas": ["MDSvrB", "MDSvrA"], "learners": [],
                    "state": "RECOVERING"}
        records = [{"partitionId": current["partitionId"],
                    "value": current, "desired": draining}]
        with self.assertRaisesRegex(RuntimeError, "MD_PROMOTION_UNSAFE"):
            apply_records(PoisonZk(),records,"drain-recovering",source="MDSvrA",target="MDSvrC")
        promoted={**draining,"state":"READY","assignmentVersion":12}
        with self.assertRaisesRegex(RuntimeError, "MD_PROMOTION_UNSAFE"):
            apply_records(PoisonZk(),[{"partitionId": current["partitionId"],
                        "value":draining,"desired":promoted}],"promote-ready")

    def test_learner_staging_cannot_mutate_other_placement_fields(self):
        current=assignment()
        staged={**current,"assignmentVersion":11,"learners":["MDSvrC"]}
        staged["nodePool"]="foreign"
        with self.assertRaisesRegex(ValueError, "unexpectedly modified"):
            validate_transition(current,staged,"stage-learner",learner="MDSvrC")

    def test_staging_never_sends_unbounded_learner_assignments_to_zk(self):
        class ReadOnlyZk:
            calls = 0
            def read_all(self, count):
                self.calls += 1
                result=[]
                for idx in range(count):
                    row=assignment().copy()
                    row["partitionId"]=f"P{idx:03d}"
                    result.append({"partitionId":row["partitionId"],"value":row,"version":3})
                return result
        zk=ReadOnlyZk()
        with tempfile.TemporaryDirectory() as temp:
            plan=str(Path(temp)/"plan.json")
            args=SimpleNamespace(partitions=12,limit=8,apply=False,learner="MDSvrC",
                                 partition_root="/dc/cluster/mdsvr/partitions",plan=plan,
                                 batch_size=8)
            command_stage(args,zk)
            with open(plan, encoding="utf-8") as stream:
                data=json.load(stream)
            self.assertEqual(8,len(data["records"]))
            self.assertEqual(4,data["remainingUnstaged"])
            self.assertEqual("P000",data["records"][0]["partitionId"])
            args.apply=True;args.limit=9
            with self.assertRaisesRegex(ValueError,"limited to eight"):
                command_stage(args,zk)
            self.assertEqual(1,zk.calls)

    def test_drain_cli_accepts_exact_partition_option(self):
        args = parser().parse_args(
            [
                "drain-recovering",
                "--from-node",
                "MDSvrA",
                "--to-node",
                "MDSvrC",
                "--partition",
                "P132",
                "--since",
                "2026-09-13T12:38:42Z",
                "--plan",
                "plan.json",
            ]
        )
        self.assertEqual(["P132"], args.partition)


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
