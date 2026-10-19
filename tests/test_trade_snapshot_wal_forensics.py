"""No-live-mutation tests for Trade snapshot/WAL incident evidence."""
import json
from pathlib import Path
import tempfile
import unittest

try:
    from tests.trade_snapshot_wal_forensics import audit
except ModuleNotFoundError:
    from trade_snapshot_wal_forensics import audit


class TradeSnapshotJournalIncidentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.logs = root / "logs"
        self.logs.mkdir()
        for node in ("TradeSvrA", "TradeSvrB"):
            (self.data / node / "journal" / ".archive").mkdir(parents=True)
            (self.logs / (node + ".log")).write_text("")
        base = self.data / "TradeSvrA"
        (base / "snapshot" / "P200").mkdir(parents=True)
        (base / "journal" / "P200").mkdir(parents=True)
        (base / "snapshot" / "P200" / "latest.json").write_text(
            json.dumps({"partitionId": "P200", "epoch": 3,
                        "snapshotSeq": 284088, "committedStateSeq": 284087}))
        (base / "journal" / "P200" / "baseline.properties").write_text(
            "baselineSeq=282050\ncommitMarkerSeq=282050\n"
            "committedStateSeq=282049\nepoch=3\nsnapshotId=verified-0\n")
        (base / "journal" / ".archive" / "P200-epoch3-seq282051-1791921308418").mkdir()
        (self.logs / "TradeSvrA.log").write_text(
            "java.lang.IllegalStateException: TradeSvr snapshot is ahead of local journal "
            "partition=P200, snapshotSeq=284088, localLastSeq=282051\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_readonly_report_never_authorizes_repair(self):
        result = audit(self.data, self.logs)
        self.assertEqual(result["incidentPartitions"], 1)
        self.assertEqual(result["totalReportedTailGap"], 2037)
        self.assertEqual(result["decision"], "BLOCKED")
        incident = result["incidents"][0]
        self.assertEqual(incident["activeJournalBaseline"]["baselineSeq"], 282050)
        self.assertEqual(incident["archiveDirectoryEvidence"]["maxArchivedDirectoryTailSeq"], 282051)
        self.assertTrue(incident["snapshotMatchesObservedFailure"])
        self.assertFalse(incident["physicalCQContentsProven"])
        self.assertFalse(result["archiveDeletionAuthorized"])
        self.assertFalse(result["recoveryAuthorized"])

    def test_baseline_only_is_not_proof_of_missing_tail(self):
        # A physical CQ might contain newer records than its baseline, and
        # this tool must not declare data permanently lost.
        result = audit(self.data, self.logs)
        self.assertFalse(result["chroniclePhysicalTailVerified"])
        self.assertNotIn("permanentDataLoss", result)

    def test_raw_cq_markers_cannot_grant_commit_proof(self):
        journal = self.data / "TradeSvrA" / "journal" / "P200"
        (journal / "20261013F.cq4").write_bytes(
            b"begin-UDIwMA==\t3\t282051\tevent\n"
            b"UDIwMA==\t3\t282052\tevent\n"
            b"UDIwMA==\t3\t282053\tevent\n")
        result = audit(self.data, self.logs, scan_cq_markers=True)
        physical = result["incidents"][0]["rawChronicleByteEvidence"]
        self.assertEqual(physical["maxRawRecordMarkerSeq"], 282053)
        self.assertEqual(physical["rawPrefixGaps"], [])
        self.assertEqual(physical["rawMarkersBeyondReportedRuntimeTail"], 2)
        self.assertFalse(physical["walRecordFramingAndCommitAuthenticated"])
        self.assertFalse(result["recoveryAuthorized"])

    def test_snapshot_partition_mismatch_fails_closed(self):
        path = self.data / "TradeSvrA" / "snapshot" / "P200" / "latest.json"
        payload = json.loads(path.read_text())
        payload["partitionId"] = "P201"
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            audit(self.data, self.logs)


if __name__ == "__main__":
    unittest.main()
