import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("verify_order_cluster_assignments.py")
SPEC = importlib.util.spec_from_file_location("order_assignment_verify", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OrderClusterAssignmentVerifyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_fixture(self, assignments, snapshot_epoch=None):
        assignment_path = self.root / "assignments.jsonl"
        assignment_path.write_text(
            "".join(json.dumps(row) + "\n" for row in assignments),
            encoding="utf-8",
        )
        for row in assignments:
            nodes = [row["primary"]] + row["replicas"] + row.get("learners", [])
            for node in nodes:
                path = self.root / node / "snapshot" / row["partitionId"] / "snapshot.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                epoch = snapshot_epoch if snapshot_epoch is not None else row["epoch"]
                path.write_text(
                    json.dumps(
                        {"partitionId": row["partitionId"], "epoch": epoch, "books": []}
                    ),
                    encoding="utf-8",
                )
        return assignment_path

    def assignments(self):
        return [
            {
                "partitionId": "P000",
                "epoch": 70,
                "primary": "OrderSvrA",
                "replicas": ["OrderSvrB"],
                "learners": ["OrderSvrC"],
                "state": "READY",
            },
            {
                "partitionId": "P001",
                "epoch": 71,
                "primary": "OrderSvrB",
                "replicas": ["OrderSvrA"],
                "learners": ["OrderSvrC"],
                "state": "READY",
            },
        ]

    def test_mixed_partition_epochs_are_valid(self):
        path = self.write_fixture(self.assignments())
        result = MODULE.verify(str(path), 2, str(self.root), verify_learners=True)
        self.assertTrue(result["mixedEpochs"])
        self.assertEqual({70: 1, 71: 1}, result["epochCounts"])

    def test_snapshot_must_match_its_partition_epoch(self):
        path = self.write_fixture(self.assignments(), snapshot_epoch=70)
        with self.assertRaisesRegex(ValueError, "snapshot epoch mismatch P001"):
            MODULE.verify(str(path), 2, str(self.root), verify_learners=False)

    def test_mismatched_snapshots_expose_only_safe_replication_watermarks(self):
        path = self.write_fixture(self.assignments())
        target = self.root / "OrderSvrA" / "snapshot" / "P000" / "snapshot.json"
        example = json.loads(target.read_text(encoding="utf-8"))
        example.update({
            "snapshotSeq": 581136,
            "committedStateSeq": 578109,
            "commitMarkerSeq": 578110,
            "books": [{"orders": [{"UserID": "must-never-leak"}]}],
        })
        target.write_text(json.dumps(example), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "assigned snapshot mismatch: P000") as raised:
            MODULE.verify(str(path), 2, str(self.root), verify_learners=False)
        message = str(raised.exception)
        self.assertIn("OrderSvrA:epoch=70,snapshotSeq=581136", message)
        self.assertIn("committedStateSeq=578109", message)
        self.assertIn("commitMarkerSeq=578110", message)
        self.assertIn("orders=1", message)
        self.assertIn("OrderSvrB:epoch=70,snapshotSeq=None", message)
        self.assertIn("sha12=", message)
        self.assertNotIn("must-never-leak", message)
        self.assertNotIn("UserID", message)

    def test_duplicate_partition_rows_are_rejected(self):
        rows = self.assignments()
        path = self.write_fixture([rows[0], rows[0]])
        with self.assertRaisesRegex(ValueError, "duplicate partitionId"):
            MODULE.verify(str(path), 2, str(self.root), verify_learners=False)


if __name__ == "__main__":
    unittest.main()
