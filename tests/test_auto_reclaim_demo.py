"""Safe disk janitor tests: never delete active WAL or real archived CQ."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from collections import namedtuple

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("disk_reclaimer", HERE / "scripts/auto-reclaim-demo.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)
Usage = namedtuple("Usage", ["total", "used", "free"])

class ReclaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "log").mkdir()
        self.now = time.time()
        self.opts = dict(gc.DEFAULTS, enabled=True, environment="demo",
                         rotatedLogRetentionDays=2, emptyBootstrapRetentionDays=2,
                         maxDeletedFilesPerRun=100, maxDeletedBytesPerRun=1_073_741_824)
    @staticmethod
    def pressured(_):
        return Usage(100*1024**3, 80*1024**3, 20*1024**3)
    @staticmethod
    def healthy(_):
        return Usage(100*1024**3, 10*1024**3, 90*1024**3)
    def age(self, file, days=4):
        import os
        stamp = self.now - days*86400
        os.utime(file, (stamp, stamp))
    def test_disabled_always_noop(self):
        f = self.root / "log" / "OrderSvrA.log.2026-10-01"
        f.write_text("old")
        self.age(f)
        self.opts["enabled"] = False
        r = gc.run_once(self.root, self.opts, now=self.now, disk_reader=self.pressured,
                        open_probe=lambda _: False)
        self.assertEqual("DISABLED", r["decision"])
        self.assertTrue(f.exists())
    def test_low_disk_usage_still_deletes_expired_rotated_log(self):
        f = self.root / "log" / "OrderSvrA.log.2026-10-01"
        f.write_text("old")
        self.age(f)
        r = gc.run_once(self.root, self.opts, now=self.now, disk_reader=self.healthy,
                        open_probe=lambda _: False)
        self.assertEqual("RETENTION_APPLIED", r["decision"])
        self.assertFalse(f.exists())
        self.assertEqual("RETENTION_DAYS_ONLY", r["policy"])
        self.assertEqual(1, r["deletedFiles"])
    def test_delete_rotated_log_but_not_current_or_under_data(self):
        f = self.root / "log" / "OrderSvrA.log.2026-10-01"
        live = self.root / "log" / "OrderSvrA.log"
        wal = self.root / "data" / "OrderSvrA" / "journal" / "P001" / "20261001F.cq4"
        f.write_text("old"); live.write_text("live")
        wal.parent.mkdir(parents=True); wal.write_text("live WAL")
        self.age(f); self.age(wal)
        r = gc.run_once(self.root, self.opts, now=self.now, disk_reader=self.pressured,
                        open_probe=lambda _: False)
        self.assertFalse(f.exists())
        self.assertTrue(live.exists())
        self.assertTrue(wal.exists())
        self.assertEqual(1, r["deletedByClass"]["rotated_log"])
    def test_never_delete_archive_with_real_cq_segment(self):
        p = self.root/"data"/"OrderSvrA"/"journal"/".archive"/"P002-epoch0-seq0-42"
        p.mkdir(parents=True)
        meta=p/"metadata.cq4t"; meta.write_bytes(bytes(131072)); self.age(meta)
        cq=p/"20261001F.cq4"; cq.write_text("COMMITTED BUSINESS DATA"); self.age(cq)
        self.age(p)
        self.assertIsNone(gc.classify_archive(p))
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.pressured,
                      open_probe=lambda _: False)
        self.assertEqual(0,r["deletedFiles"])
        self.assertTrue(cq.exists())
    def test_empty_bootstrap_reclaimed_only_without_open_handle(self):
        p=self.root/"data"/"OrderSvrB"/"journal"/".archive"/"P001-epoch0-seq0-42"
        p.mkdir(parents=True)
        meta=p/"metadata.cq4t"; meta.write_bytes(bytes(131072)); self.age(meta); self.age(p)
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.pressured,
                      open_probe=lambda _: True)
        self.assertEqual(1,r["blockedCandidates"]); self.assertTrue(meta.exists())
        self.assertEqual("open_or_unverifiable_file_handle", next(iter(r["blockedReasons"])))
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.pressured,
                      open_probe=lambda _: False)
        self.assertEqual(1,r["deletedFiles"])
        self.assertFalse(p.exists())
    def test_unknown_open_state_fails_closed(self):
        f=self.root/"log"/"TradeSvr.log.2026-10-01"
        f.write_text("old"); self.age(f)
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.pressured,
                      open_probe=lambda _: None)
        self.assertTrue(f.exists())
        self.assertEqual(1,r["blockedCandidates"])
    def test_budgets_and_recent_logs(self):
        a=self.root/"log"/"OrderSvrA.log.2026-10-01"
        b=self.root/"log"/"OrderSvrB.log.2026-10-01"
        recent=self.root/"log"/"OrderSvrC.log.2026-10-10"
        for f in (a,b,recent): f.write_text("r"*100)
        self.age(a); self.age(b)
        self.opts["maxDeletedFilesPerRun"]=1
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.pressured,
                      open_probe=lambda _: False)
        self.assertEqual(1,r["deletedFiles"])
        self.assertTrue(recent.exists())
        self.assertEqual(1,sum([a.exists(),b.exists()]))
    def test_disk_usage_is_only_telemetry_not_a_deletion_condition(self):
        f=self.root/"log"/"APSSvr.log"
        f.write_text("live")
        r=gc.run_once(self.root,self.opts,now=self.now,
                      disk_reader=lambda _: Usage(100*1024**3,95*1024**3,5*1024**3),
                      open_probe=lambda _: False)
        self.assertEqual("RETENTION_APPLIED",r["decision"])
        self.assertNotIn("pressureThresholdReached",r)
        self.assertEqual(95.0,r["usedPercentBefore"])
        self.assertTrue(f.exists())
    def test_legacy_disk_watermark_config_is_rejected(self):
        import json
        f=self.root/'old_config.json'
        f.write_text(json.dumps(dict(self.opts, highWatermarkPercent=75)))
        with self.assertRaisesRegex(ValueError,'unknown config keys'):
            gc.load_config(f)

    def test_candidate_scan_count_is_bounded(self):
        for i in range(8):
            f=self.root/'log'/f'Order{i}.log.2026-10-01'
            f.write_text('old'); self.age(f)
        self.opts['maxCandidatesPerRun']=3
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.healthy,
                      open_probe=lambda _: False)
        self.assertEqual(3,r['deletedFiles'])
        self.assertIn('CANDIDATE_BUDGET_REACHED',r['warnings'])
        self.assertEqual(5,len(list((self.root/'log').iterdir())))

    def test_daily_round_robin_does_not_starve_archives_with_open_handles(self):
        for i in range(8):
            f=self.root/'log'/f'Order{i}.log.2026-10-01'
            f.write_text('expired but open'); self.age(f)
        self.opts['maxCandidatesPerRun']=3
        checked=[]
        cursor=0
        for _ in range(3):
            r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.healthy,
                          candidate_cursor=cursor,
                          open_probe=lambda f: checked.append(f.name) or True)
            cursor=r['nextCandidateCursor']
        self.assertEqual(8,len(set(checked)))
        self.assertEqual(8,len(list((self.root/'log').iterdir())))

    def test_production_configuration_never_enables_demo_cleaner(self):
        import json
        f=self.root/"cfg.json"
        f.write_text(json.dumps(dict(self.opts,environment="production")))
        with self.assertRaisesRegex(ValueError,"production"):
            gc.load_config(f)
        f.write_text(json.dumps(dict(self.opts, enabled=False, environment="production")))
        self.assertFalse(gc.load_config(f)["enabled"])
    def test_symlinks_never_cleaned(self):
        real=self.root/"data"/"Important.cq4"; real.write_text("source WAL")
        alias=self.root/"log"/"OrderSvrA.log.2026-10-01"
        alias.symlink_to(real)
        r=gc.run_once(self.root,self.opts,now=self.now,disk_reader=self.pressured,
                      open_probe=lambda _: False)
        self.assertTrue(alias.exists()); self.assertTrue(real.exists())
        self.assertEqual(0,r["deletedFiles"])

if __name__ == "__main__":
    unittest.main()
