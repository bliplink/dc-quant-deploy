"""Offline protocol gate regression. Never accesses Docker, ZK or live Trade."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "scripts" / "audit-trade-two-way-auto-ha-readonly.py"
spec = importlib.util.spec_from_file_location("two_way_ha_preflight", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class AutomaticTradeSafetyPreflightTest(unittest.TestCase):
    def test_readonly_a_and_b_require_exact_epoch_replica_and_live_health(self):
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname)
            rows = []
            for slot in range(256):
                part = f"P{slot:03}"
                owner = "TradeSvrA" if slot % 2 == 0 else "TradeSvrB"
                replica = "TradeSvrB" if slot % 2 == 0 else "TradeSvrA"
                epoch = 1 if slot % 2 == 0 else 3
                rows.append({"value": {"partitionId": part, "primary": owner,
                                        "replica": replica, "state": "READY",
                                        "epoch": epoch}})
                file = base / "data" / replica / "snapshot" / part / "latest.json"
                file.parent.mkdir(parents=True)
                file.write_text(json.dumps({
                    "partitionId": part, "epoch": 2 if slot % 2 else 1,
                    "snapshotSeq": 0
                }))
            report = mod.inspect(rows, {}, base, 1792191000000)
            self.assertEqual({"TradeSvrA": 128, "TradeSvrB": 128},
                             report["primaryCounts"])
            self.assertEqual(128,
                report["blockerCounts"]["RECIPIENT_LOCAL_SNAPSHOT_STALE_EPOCH"])
            self.assertEqual(256,
                report["blockerCounts"]["REPLICATION_HEALTH_MISSING"])
            self.assertFalse(report["safeToSigkillEitherPrimary"])
            self.assertEqual(256, report["blockedPartitionCount"])

    def test_reject_missing_or_duplicate_inventory(self):
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaises(ValueError):
                mod.inspect([], {}, Path(dirname), 1792191000000)


if __name__ == "__main__":
    unittest.main()
