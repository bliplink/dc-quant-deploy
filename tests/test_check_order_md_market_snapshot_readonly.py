"""Negative tests for read-only full Order market snapshot preflight."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("audit", Path(__file__).parent / "check_order_md_market_snapshot_readonly.py")
auditmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auditmod)


class OrderMdMarketSnapshotAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.market = "FAKE01"
        self.partition = auditmod.partition(self.market)
        self.body = dict(
            version=1, partitionId=self.partition, epoch=2, snapshotSeq=100,
            committedStateSeq=99, committedStateEpoch=2, commitMarkerSeq=100,
            books=[dict(location=self.market, marketIndicator="4", securityId="BTCUSDT", lastUpdateId=7)],
        )
        self.write_all()

    def write_all(self):
        for node in ("OrderSvrA", "OrderSvrB", "OrderSvrC"):
            file = self.root / node / "snapshot" / self.partition / "snapshot.json"
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(self.body, sort_keys=True))

    def check(self):
        return auditmod.audit(self.root, [{"location": self.market}])

    def test_matching_three_nodes_still_never_grants_promotion(self):
        result = self.check()
        self.assertEqual(3, result["snapshots"][0]["matchedNodes"])
        self.assertEqual(1, result["verifiedTriplicateSnapshots"])
        self.assertFalse(result["promotionAuthorized"])
        self.assertEqual("BLOCKED", result["decision"])

    def test_valid_noncommit_tail_snapshot_remains_replicated_but_not_promotable(self):
        # A persisted snapshot may include journal events after the last
        # committed business-state marker. This is a consistency observation,
        # not authorization to replay uncommitted tail or promote MD.
        self.body["snapshotSeq"] = 105
        self.write_all()
        result = self.check()
        self.assertEqual(1, result["verifiedTriplicateSnapshots"])
        self.assertEqual([], result["snapshotIssues"])
        self.assertFalse(result["promotionAuthorized"])
        self.assertEqual("BLOCKED", result["decision"])

    def test_commit_marker_beyond_snapshot_tail_is_invalid(self):
        self.body["commitMarkerSeq"] = 101
        self.write_all()
        self.assertTrue(self.check()["snapshotIssues"])

    def test_missing_replica_fails_closed(self):
        (self.root/"OrderSvrC"/"snapshot"/self.partition/"snapshot.json").unlink()
        self.assertTrue(self.check()["snapshotIssues"])

    def test_old_or_mismatching_snapshot_fails_closed(self):
        file = self.root/"OrderSvrB"/"snapshot"/self.partition/"snapshot.json"
        altered = dict(self.body, epoch=1, committedStateEpoch=1)
        file.write_text(json.dumps(altered))
        self.assertIn(self.partition+":ORDER_REPLICA_SNAPSHOT_MISMATCH", self.check()["snapshotIssues"])

    def test_wrong_market_and_marker_fail_closed(self):
        self.body["books"][0]["location"] = "WRONG"
        self.write_all()
        self.assertTrue(self.check()["snapshotIssues"])
        self.body["books"][0]["location"] = self.market
        self.body["commitMarkerSeq"] = 0
        self.write_all()
        self.assertTrue(self.check()["snapshotIssues"])

    def test_other_market_from_wrong_partition_is_rejected(self):
        self.body["books"].append(dict(location="ELSE99", marketIndicator="4",
                                       securityId="ETHUSDT", lastUpdateId=8))
        self.write_all()
        self.assertTrue(self.check()["snapshotIssues"])

    def test_cross_epoch_commit_watermark_regression_is_rejected(self):
        self.body["committedStateEpoch"] = 3
        self.write_all()
        self.assertTrue(self.check()["snapshotIssues"])

    def test_duplicate_tenant_not_authorized(self):
        result = auditmod.audit(self.root, [{"location": self.market}, {"location": self.market}])
        self.assertIn("INVALID_OR_DUPLICATE_TENANT", result["snapshotIssues"])


if __name__ == "__main__":
    unittest.main()