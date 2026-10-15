import tempfile
import unittest
from pathlib import Path
from tests import check_trade_live_snapshot_role_preflight as gate
from tests.verify_trade_rollout_snapshot_headroom import SnapshotEvidenceError


def rowset(tenant,epoch=1):
    part=gate.location_partition(tenant)
    items=[{"partitionId":"P%03d"%i,"epoch":1,"state":"READY",
            "primary":"TradeSvrA","replica":"TradeSvrB","replicas":["TradeSvrB"]}
           for i in range(256)]
    item=items[int(part[1:])]
    item.update({"primary":"TradeSvrB","replica":"TradeSvrA",
                 "replicas":["TradeSvrA"],"epoch":epoch})
    return items,part


def snapshot(root,node,part,tenant,epoch,seq):
    import json
    path=root/node/"snapshot"/part/"latest.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"partitionId":part,"snapshotId":"snap",
       "epoch":epoch,"snapshotSeq":seq,"committedStateSeq":max(seq-1,0),
       "committedStateEpoch":epoch,"locations":[tenant]}))


class TradeLiveSnapshotRolePreflightTests(unittest.TestCase):
    def test_stale_primary_epoch_and_behind_replica_block(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows,p=rowset("TENANT1",3)
            snapshot(root,"TradeSvrB",p,"TENANT1",1,100)
            snapshot(root,"TradeSvrA",p,"TENANT1",2,50)
            result=gate.evaluate(rows,root,["TENANT1"])
            self.assertEqual(1,result["snapshotBlocked"])
            self.assertIn("PRIMARY_SNAPSHOT_STALE_EPOCH_OR_EMPTY",
                          result["snapshotIssues"][0]["issues"])
            self.assertIn("REPLICA_SNAPSHOT_EPOCH_MISMATCH",
                          result["snapshotIssues"][0]["issues"])
            self.assertFalse(result["authorizesPrimarySigkill"])

    def test_old_epoch_with_higher_sequence_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows,p=rowset("TENANT1",4)
            snapshot(root,"TradeSvrB",p,"TENANT1",4,120)
            snapshot(root,"TradeSvrA",p,"TENANT1",3,9999)
            result=gate.evaluate(rows,root,["TENANT1"])
            self.assertEqual(1,result["snapshotBlocked"])
            self.assertIn("REPLICA_SNAPSHOT_EPOCH_MISMATCH",
                          result["snapshotIssues"][0]["issues"])
            self.assertFalse(result["authorizesPrimarySigkill"])

    def test_equal_snapshot_is_still_unproven_and_cannot_authorize(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows,p=rowset("TENANT1")
            for node in ("TradeSvrA","TradeSvrB"):
                snapshot(root,node,p,"TENANT1",1,50)
            result=gate.evaluate(rows,root,["TENANT1"])
            self.assertEqual(0,result["snapshotBlocked"])
            self.assertEqual("UNPROVEN",result["snapshotPreflight"])
            self.assertFalse(result["authorizesReplicaRestart"])

    def test_replica_primary_only_snapshot_policy_does_not_infer_wal_data_loss(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows,p=rowset("TENANT1")
            snapshot(root,"TradeSvrB",p,"TENANT1",1,120)
            # This matches the live Mac configuration: only the Primary
            # runs TradeSnapshotScheduler, while Replica retains cold image.
            snapshot(root,"TradeSvrA",p,"TENANT1",1,0)
            result=gate.evaluate(rows,root,["TENANT1"])
            issues=result["snapshotIssues"][0]["issues"]
            self.assertIn("REPLICA_SNAPSHOT_STALE_WAL_HEAD_NOT_CHECKED",issues)
            self.assertEqual("UNPROVEN_FROM_SNAPSHOT_FILES",
                             result["replicaWalBehindOrDivergent"])
            self.assertEqual("PRIMARY_ONLY_PERIODIC_SCHEDULER",
                             result["replicaSnapshotPolicy"])
            self.assertEqual("NOT_CHECKED",result["walCommittedHeadAndAckProof"])
            self.assertFalse(result["authorizesPrimarySigkill"])
            self.assertFalse(result["authorizesReplicaRestart"])

    def test_missing_snap_and_bad_catalog_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows,p=rowset("TENANT1")
            snapshot(root,"TradeSvrB",p,"TENANT1",1,50)
            result=gate.evaluate(rows,root,["TENANT1"])
            self.assertIn("REPLICA_SNAPSHOT_MISSING",result["snapshotIssues"][0]["issues"])
            with self.assertRaises(SnapshotEvidenceError):
                gate.evaluate(rows[:-1],root,["TENANT1"])
            with self.assertRaises(SnapshotEvidenceError):
                gate.evaluate(rows,root,["TENANT1","TENANT1"])
