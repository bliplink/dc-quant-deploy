import tempfile
import unittest
from pathlib import Path

from tests.audit_saas_wal_archives_readonly import inventory, NODES


class ArchiveInventoryTest(unittest.TestCase):
    def fixture(self, root):
        for name in NODES:
            journal = root / name / "journal"
            (journal / ".archive").mkdir(parents=True)
            active=journal/"P023"
            active.mkdir()
            (active/"metadata.cq4t").write_bytes(b"metadata")

    def test_sparse_allocated_byte_accounting_never_authorizes_gc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            aged=root/NODES[0]/"journal"/".archive"/"P023-epoch1-seq100-1000"
            aged.mkdir()
            (aged/"20261012F.cq4").write_bytes(b"committed")
            v=inventory(root,172800000+2000,172800000)
            self.assertEqual(1,v["summary"]["archiveDirectories"])
            self.assertEqual(1,v["summary"]["agedCandidateDirectories"])
            self.assertEqual(0,v["summary"]["deletionAuthorized"])
            self.assertFalse(v["serviceNodes"][0]["retireAllowed"])
            self.assertGreater(v["summary"]["archiveAllocatedBytes"],0)

    def test_symlink_and_unknown_archive_are_not_gc_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            sub=root/NODES[0]/"journal"/".archive"
            (sub/"unrecognized").mkdir()
            (sub/"P023-epoch1-seq100-1000").symlink_to(sub/"unrecognized")
            v=inventory(root,172800000+2000,172800000)
            self.assertEqual(0,v["summary"]["archiveDirectories"])
            self.assertGreaterEqual(v["summary"]["unsafeOrUnknownEntries"],2)
            self.assertEqual(0,v["summary"]["deletionAuthorized"])

    def test_archive_count_and_root_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            base=root/NODES[0]/"journal"/".archive"
            for i in range(3):
                (base/f"P023-epoch1-seq{i+1}-{1000+i}").mkdir()
            with self.assertRaisesRegex(ValueError,"bound"):
                inventory(root,172800000+2000,172800000,max_segments=2)
            (root/NODES[0]/"journal"/"P023"/"metadata.cq4t").unlink()
            (root/NODES[0]/"journal"/"P023").rmdir()
            self.assertEqual(0,inventory(root,172800000+2000,172800000)["summary"]["deletionAuthorized"])
