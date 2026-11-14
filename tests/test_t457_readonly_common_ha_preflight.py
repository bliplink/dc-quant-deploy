#!/usr/bin/env python3
"""Unit tests of the read-only T457 release gate; no Docker or ZooKeeper calls."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("t457_readonly_common_ha_preflight.py")
spec = importlib.util.spec_from_file_location("t457_ha", SOURCE)
ha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ha)


class CertifiedHaPreflightTests(unittest.TestCase):
    def fixture(self, drop=None, duplicate=None):
        lines = ["NPC1|2"]
        for n in range(256):
            if n == drop:
                continue
            primary = "A" if n < 128 else "B"
            replica = "B" if n < 128 else "A"
            lines.append(
                "P{:03d}|2|{}|{}|STRICT_QUORUM|READY".format(
                    n, primary, replica
                )
            )
        if duplicate is not None:
            lines.append(lines[duplicate + 1])
        return "\n".join(lines)

    def base_result(self):
        pin = "a" * 64
        good_manifest = ha.manifest_summary(ha.parse_manifest(self.fixture()))
        nodes = {
            x: {
                "common_sha": pin,
                "watch_threads": 2,
                "network_mode": "host",
            }
            for x in ("order-a", "order-b", "trade-a", "trade-b")
        }
        return {"manifest": {"order": good_manifest, "trade": good_manifest},
                "nodes": nodes}, pin

    def test_complete_balanced_manifest(self):
        rows = ha.parse_manifest(self.fixture())
        summary = ha.manifest_summary(rows)
        self.assertTrue(summary["balanced_128_128"])
        self.assertEqual(summary["partitions"], 256)
        self.assertEqual(summary["policies"], {"STRICT_QUORUM": 256})

    def test_incomplete_manifest_rejected(self):
        with self.assertRaises(ha.ProbeError):
            ha.parse_manifest(self.fixture(drop=60))

    def test_duplicate_manifest_rejected(self):
        with self.assertRaises(ha.ProbeError):
            ha.parse_manifest(self.fixture(duplicate=60))

    def test_wrong_layout_rejected(self):
        report, pin = self.base_result()
        rows = ha.parse_manifest(self.fixture())
        rows["P060"].update(primary="B", replica="A")
        rows["P180"].update(primary="A", replica="B")
        summary = ha.manifest_summary(rows)
        self.assertTrue(summary["balanced_128_128"])
        report["manifest"]["order"] = summary
        self.assertIn("ORDER_256_HOME_CENSUS_FAIL", ha.verify(report, pin))

    def test_degraded_policy_rejected_even_when_home_and_ready(self):
        report, pin = self.base_result()
        rows = ha.parse_manifest(self.fixture())
        rows["P060"]["policy"] = "LOCAL_DURABLE_ASYNC"
        report["manifest"]["trade"] = ha.manifest_summary(rows)
        self.assertIn("TRADE_NOT_ALL_STRICT_QUORUM", ha.verify(report, pin))

    def test_all_facts_present_is_preflight_only(self):
        report, pin = self.base_result()
        self.assertEqual(ha.verify(report, pin), [])

    def test_missing_watch_and_jar_mismatch_fail_closed(self):
        report, pin = self.base_result()
        report["nodes"]["order-b"]["common_sha"] = "b" * 64
        report["nodes"]["trade-a"]["watch_threads"] = 0
        failures = ha.verify(report, pin)
        self.assertIn("COMMON_JAR_SHA_MISMATCH", failures)
        self.assertIn("TRADE_A_AUTO_WATCH_ABSENT", failures)


if __name__ == "__main__":
    unittest.main()
