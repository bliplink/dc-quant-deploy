"""Archive retention inventory MUST be incapable of deleting active or archived WAL."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

MOD = Path(__file__).resolve().parents[1] / "scripts/audit-order-archive-retention.py"
SPEC = importlib.util.spec_from_file_location("archive_audit", MOD)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ReadOnlyRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "OrderSvrA" / "journal"
        (self.root / ".archive").mkdir(parents=True)
        self.active = self.root / "P246" / "active.cq4"
        self.active.parent.mkdir()
        self.active.write_bytes(b"ACTIVE-COMMITTED-WAL")
        self.archived = self.root / ".archive" / "P246-epoch1-seq578111-1791580899185"
        self.archived.mkdir()
        self.marker = self.archived / "20261009F.cq4"
        self.marker.write_bytes(b"STATE_COMMIT RECORD")

    def test_protected_archives_are_only_reported_not_deleted(self):
        result = audit.inventory(self.root)
        self.assertEqual(1, result["archives"])
        detail = result["archiveDetails"][0]
        self.assertEqual("P246", detail["partition"])
        self.assertEqual(578111, detail["lastSequenceNameHint"])
        self.assertEqual("HOLD", detail["retentionDecision"])
        self.assertFalse(detail["deletionAuthorized"])
        self.assertIn("REPLICA_RECOVERY_NOT_ATTESTED", detail["blockedBy"])
        self.assertEqual(b"STATE_COMMIT RECORD", self.marker.read_bytes())
        self.assertEqual(b"ACTIVE-COMMITTED-WAL", self.active.read_bytes())

    def test_name_age_never_grants_deletion(self):
        old = self.root / ".archive" / "P002-epoch1-seq1-1"
        old.mkdir()
        (old / "old.cq4").write_bytes(b"old-but-still-pinned")
        reports = audit.inventory(self.root)["archiveDetails"]
        self.assertTrue(all(x["retentionDecision"] == "HOLD" for x in reports))

    def test_unsafe_symlink_is_rejected(self):
        alias = self.root / ".archive" / "P003-epoch1-seq3-100"
        alias.symlink_to(self.archived, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            audit.inventory(self.root)

    def test_bad_metadata_is_rejected(self):
        (self.root / ".archive" / "unexpected").mkdir()
        with self.assertRaisesRegex(ValueError, "unexpected archive"):
            audit.inventory(self.root)

    def test_journal_path_symlink_is_rejected(self):
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "nonsymlink"):
            audit.inventory(alias)

    def test_duplicate_input_never_authorizes_deletion(self):
        result1 = audit.inventory(self.root)
        result2 = audit.inventory(self.root)
        self.assertEqual(result1["archiveDetails"], result2["archiveDetails"])
        self.assertFalse(any(x["deletionAuthorized"] for x in result1["archiveDetails"]))

    def test_cli_writes_only_outside_journal(self):
        out = Path(self.temp.name) / "audit.json"
        self.assertEqual(0, audit.main(["--journal", str(self.root), "--output", str(out)]))
        self.assertIn('"deletionAuthorized": false', out.read_text())
        with self.assertRaisesRegex(ValueError, "must not be written"):
            audit.main(["--journal", str(self.root), "--output", str(self.root / "bad.json")])


if __name__ == "__main__":
    unittest.main()
