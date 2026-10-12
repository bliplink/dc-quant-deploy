import json
import tempfile
import unittest
from pathlib import Path

from tests.verify_trade_rollout_snapshot_headroom import inspect, read_metadata, SnapshotEvidenceError


def snap(root, part, locations, seq, committed=None, epoch=2):
    p = root / part / "latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump({"version":2, "snapshotId":part + "-snap-" + str(seq),
                   "partitionId":part, "locations":locations, "epoch":epoch,
                   "snapshotSeq":seq, "committedStateSeq":seq if committed is None else committed,
                   "committedStateEpoch":epoch, "createdAt":1,
                   "executionDedupe":{"applied":[{"key":"x","result":{"msg":"a"}}],
                                      "terminalOrders":[]}}, f)
    return p


class TradeSnapshotHeadroomTest(unittest.TestCase):
    def test_blocks_stale_target_even_if_old_snapshot_is_parseable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snap(root / "A", "P023", ["TENANT_X"], 200)
            snap(root / "B", "P023", ["TENANT_X"], 150)
            result = inspect(root / "A", root / "B", 1)
            self.assertEqual("BLOCK", result["fastSnapshotPreflight"])
            self.assertEqual("target_full_snapshot_behind", result["blocked"][0]["reason"])
            self.assertFalse(result["authorizesPrimaryRestart"])

    def test_equal_full_snapshots_are_still_not_wal_durability_proof(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snap(root / "A", "P023", ["TENANT_X"], 200)
            snap(root / "B", "P023", ["TENANT_X"], 200)
            result = inspect(root / "A", root / "B", 1)
            self.assertEqual("UNPROVEN", result["fastSnapshotPreflight"])
            self.assertFalse(result["authorizesPrimaryRestart"])
            self.assertEqual("NOT_CHECKED", result["walAndReplicaAckProof"])

    def test_scope_fail_closed_when_no_active_partitions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snap(root / "A", "P023", [], 1)
            (root / "B").mkdir()
            with self.assertRaises(SnapshotEvidenceError):
                inspect(root / "A", root / "B", 1)

    def test_missing_target_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snap(root / "A", "P023", ["TENANT_X"], 200)
            (root / "B").mkdir()
            self.assertEqual(1, inspect(root / "A", root / "B", 1)["blockedCount"])

    def test_extracts_bounded_metadata_without_deserializing_payload(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            f = snap(root, "P023", ["TENANT_X"], 300)
            with f.open("a") as handle:
                handle.write(" " + "x" * (1024 * 1024))
            self.assertEqual(300, read_metadata(f)["snapshotSeq"])


if __name__ == "__main__":
    unittest.main()
