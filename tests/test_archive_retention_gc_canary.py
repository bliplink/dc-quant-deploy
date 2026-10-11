"""Guarded archive GC canary must delete only its OWN disposable fixtures."""
import dataclasses
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

SRC=Path(__file__).resolve().parents[1] / "scripts/run-archive-retention-gc-canary.py"
SPEC=importlib.util.spec_from_file_location("otc_gc_canary",SRC)
canary=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=canary
SPEC.loader.exec_module(canary)


class ArchiveGcCanaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="otc-gc-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.archive=self.root/"P200-epoch3-seq120-123456"
        self.archive.mkdir()
        self.payload=self.archive/"data-0000.cq4"
        self.payload.write_bytes(b"TEST CQ DATA")
        old=time.time()-canary.MIN_AGE_SECONDS-100
        os.utime(self.payload,(old,old))
        self.proof=canary.RetentionWitness("P200",120,125,(120,121),125,
                backup_verified=True,readers_active=0,source_recoverable=True,
                now=time.time())

    def test_complete_proof_reaches_safe_decision(self):
        self.assertTrue(canary.require_gc_safe(self.archive,self.proof))
        self.assertTrue(self.payload.exists())

    def test_replica_or_projection_or_snapshot_lag_refuses_gc(self):
        for changes in ({"replica_durable":(119,121)},
                        {"projection_durable_seq":119},
                        {"snapshot_durable_seq":119},
                        {"replica_durable":(130,)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    canary.require_gc_safe(self.archive,dataclasses.replace(self.proof,**changes))
                self.assertTrue(self.payload.exists())

    def test_readers_backup_and_source_need_independent_proofs(self):
        for changes in ({"readers_active":1},
                        {"backup_verified":False},
                        {"source_recoverable":False}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                canary.require_gc_safe(self.archive,dataclasses.replace(self.proof,**changes))

    def test_age_identity_and_symlink_safety_fail_closed(self):
        with self.assertRaises(ValueError):
            canary.require_gc_safe(self.archive,self.proof,minimum_age=1)
        newer=time.time()
        os.utime(self.payload,(newer,newer))
        with self.assertRaises(ValueError):
            canary.require_gc_safe(self.archive,self.proof)
        with self.assertRaises(ValueError):
            canary.require_gc_safe(self.archive,dataclasses.replace(
                    self.proof,expected_partition="P201"))
        alias=self.root/"P999-epoch1-seq120-111"
        alias.symlink_to(self.archive,target_is_directory=True)
        with self.assertRaises(ValueError):
            canary.require_gc_safe(alias,self.proof)

    def test_actual_canary_deletes_one_and_checks_backup_restore(self):
        report=self.root/"result.json"
        result=canary.execute_canary(report)
        self.assertEqual("DISPOSABLE_TEST_ONLY_ACTUAL_DELETE",result["mode"])
        self.assertEqual(1,result["actualDeletedArchives"])
        self.assertEqual(1,result["unsafeArchivesPreserved"])
        self.assertEqual(8,len(result["negativeGatesRejected"]))
        self.assertTrue(result["canaryBackupRestoreVerified"])
        self.assertFalse(result["realChronicleBusinessRestoreProven"])
        self.assertFalse(result["productionGcEnabled"])
        self.assertTrue(report.is_file())
        with self.assertRaises(ValueError):
            canary.execute_canary(report)


if __name__=="__main__":
    unittest.main()
