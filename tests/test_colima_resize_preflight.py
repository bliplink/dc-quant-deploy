"""Offline tests for fail-closed full Colima VM resize gate."""
import copy
import unittest

from colima_resize_preflight import issues_for_snapshot


def fixture():
    return {
        "host_cpu": 10,
        "host_memory_gib": 24,
        "target_cpu": 9,
        "target_memory_gib": 18,
        "data_bytes": 90 * (1024 ** 3),
        "backup_free_bytes": 120 * (1024 ** 3),
        "backup_separate_device": True,
        "running_critical_containers": [],
        "robots_paused": True,
        "journal_consistency_verified": True,
        "projection_consistency_verified": True,
        "restore_plan_verified": True,
    }


class ColimaResizePreflightTest(unittest.TestCase):
    def test_complete_evidence_passes_only_static_preflight(self):
        self.assertEqual([], issues_for_snapshot(fixture()))

    def test_missing_evidence_is_not_go(self):
        s = fixture()
        del s["journal_consistency_verified"]
        self.assertTrue(any("missing evidence" in x for x in issues_for_snapshot(s)))

    def test_same_volume_is_not_an_independent_backup(self):
        s = fixture()
        s["backup_separate_device"] = False
        self.assertTrue(any("independent backup" in x for x in issues_for_snapshot(s)))

    def test_backup_must_have_20_percent_free_headroom(self):
        s = fixture()
        s["backup_free_bytes"] = 53 * 1024 ** 3
        self.assertTrue(any("headroom" in x for x in issues_for_snapshot(s)))

    def test_running_order_nodes_block_resize(self):
        s = fixture()
        s["running_critical_containers"] = ["dc-saas-ordersvr"]
        self.assertTrue(any("not cleanly quiesced" in x for x in issues_for_snapshot(s)))

    def test_projection_gap_blocks_resize(self):
        s = fixture()
        s["projection_consistency_verified"] = False
        self.assertTrue(any("Projection" in x for x in issues_for_snapshot(s)))

    def test_journal_uncertainty_blocks_resize(self):
        s = fixture()
        s["journal_consistency_verified"] = False
        self.assertTrue(any("journal" in x for x in issues_for_snapshot(s)))

    def test_robot_must_be_paused(self):
        s = fixture()
        s["robots_paused"] = False
        self.assertTrue(any("Robot" in x for x in issues_for_snapshot(s)))

    def test_restore_plan_required(self):
        s = fixture()
        s["restore_plan_verified"] = False
        self.assertTrue(any("restoration" in x for x in issues_for_snapshot(s)))

    def test_reserve_one_host_core_and_four_gib_ram(self):
        s = fixture()
        s["target_cpu"] = 10
        s["target_memory_gib"] = 21
        errors = issues_for_snapshot(s)
        self.assertTrue(any("host core" in x for x in errors))
        self.assertTrue(any("host macOS" in x for x in errors))

    def test_invalid_numeric_evidence_fails_closed(self):
        s = fixture()
        s["host_cpu"] = "?"
        self.assertTrue(issues_for_snapshot(s))


if __name__ == "__main__":
    unittest.main()
