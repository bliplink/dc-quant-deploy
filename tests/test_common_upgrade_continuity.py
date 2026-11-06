#!/usr/bin/env python3
"""Unit tests for read-only Upgrade/Fresh deployment continuity requirements."""
import tempfile
import unittest
from pathlib import Path

from check_common_upgrade_continuity import (
    ROLES, check, physical_root, props, role_layout,
)


def layouts(generation="t398-ready-v1", common="sha1"):
    result = {}
    for role in ROLES:
        service, node = role.split("-")
        service_name = "OrderSvr" if service == "order" else "TradeSvr"
        machine = node.upper()
        result[role] = {
            "role": role,
            "logical_root": "/srv/dc/data/%s/%s/%s%s" % (
                generation, service_name, service_name, machine),
            "physical_root": "/var/lib/docker/volumes/%s/_data/%s/%s%s" % (
                generation, service_name, service_name, machine),
            "jar_sha256": common,
            "gateway_enabled": True,
        }
    return result


def proj(generation):
    return "/var/lib/docker/volumes/%s/_data" % generation


class UpgradeContinuityTests(unittest.TestCase):
    def test_in_place_upgrade_structural_pass(self):
        new = layouts()
        self.assertEqual([], check(new, layouts(), proj("t398-ready-v1"),
                                    proj("t398-ready-v1"), False, "upgrade"))

    def test_real_t523_mismatch_detected_for_all_four_and_projection(self):
        mismatches = check(layouts("t523-ready-v1"),
                           layouts("t398-ready-v1"),
                           proj("otc-t399-services-data"),
                           proj("otc-t399-services-data"), True, "upgrade")
        for role in ROLES:
            self.assertIn("BUSINESS_WAL_SNAPSHOT_GENERATION_CHANGED:" + role,
                          mismatches)
        self.assertNotIn("PROJECTION_VOLUME_CHANGED_WITHOUT_REPLAY_PROOF",
                         mismatches)

    def test_fresh_deploy_rejects_old_projection_and_robot(self):
        problems = check(layouts("t523-ready-v1"), {},
                         proj("otc-t399-services-data"),
                         proj("otc-t399-services-data"), True, "fresh")
        self.assertIn("FRESH_DEPLOYMENT_STILL_HAS_OLD_ROBOT_WRITERS",
                      problems)
        self.assertIn("FRESH_PROJECTION_REUSES_LEGACY_CONSUMER_VOLUME",
                      problems)

    def test_projection_separate_volume_but_changed_upgrade_refused(self):
        issues = check(layouts(), layouts(), proj("new-projection-volume"),
                       proj("old-projection-volume"), False, "upgrade")
        self.assertIn("PROJECTION_VOLUME_CHANGED_WITHOUT_REPLAY_PROOF", issues)

    def test_fresh_is_only_structural_when_isolated(self):
        self.assertEqual([], check(layouts("new-empty"), {},
                                   proj("new-empty"), proj("legacy-consumer"),
                                   False, "fresh"))

    def test_different_common_jar_and_unpublished_gateway_both_refused(self):
        current = layouts()
        current["trade-a"]["jar_sha256"] = "different"
        current["order-b"]["gateway_enabled"] = False
        problems = check(current, layouts(), proj("t398-ready-v1"),
                         proj("t398-ready-v1"), False, "upgrade")
        self.assertIn("COMMON_JAR_SHA_MISMATCH_ACROSS_ORDER_TRADE", problems)
        self.assertIn("GATEWAY_NOT_CERTIFIED_PUBLISHED:order-b", problems)

    def test_unapproved_common_jar_release_refused_even_when_four_match(self):
        current = layouts(common="a" * 64)
        problems = check(current, layouts(), proj("t398-ready-v1"),
                         proj("t398-ready-v1"), False, "upgrade",
                         approved_sha256="b" * 64)
        self.assertIn("UNAPPROVED_COMMON_JAR_SHA", problems)
        self.assertNotIn("COMMON_JAR_SHA_MISMATCH_ACROSS_ORDER_TRADE", problems)

    def test_incomplete_predecessor_census_refused(self):
        old = layouts()
        del old["trade-b"]
        self.assertIn("UPGRADE_REQUIRES_ALL_FOUR_PREVIOUS_NODES",
                      check(layouts(), old, proj("t398-ready-v1"),
                            proj("t398-ready-v1"), False, "upgrade"))

    def test_physical_mapping_longest_mount_and_traversal_denial(self):
        mounts = [
            {"Destination": "/srv/dc/data", "Source": "/old-root"},
            {"Destination": "/srv/dc/data/t523-ready-v1",
             "Source": "/var/lib/docker/volumes/t523-ready-v1/_data"},
        ]
        self.assertEqual(
            "/var/lib/docker/volumes/t523-ready-v1/_data/OrderSvr/OrderSvrA",
            physical_root(mounts,
                          "/srv/dc/data/t523-ready-v1/OrderSvr/OrderSvrA"))
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_COMMON_DATAROOT"):
            physical_root(mounts, "/srv/dc/data/t523-ready-v1/../../secret")

    def test_stopped_predecessor_may_be_inspected_readonly(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            conf = root / "application.properties"
            conf.write_text(
                "order.common.nodeRuntime.dataRoot="
                "/srv/dc/data/t398-ready-v1/OrderSvr/OrderSvrB\n"
                "order.common.gatewayDiscovery.enabled=false\n")
            inspected = {
                "State": {"Running": False},
                "Mounts": [
                    {"Destination":
                     "/srv/dc/dc/OrderSvr/config/application.properties",
                     "Source": str(conf)},
                    {"Destination": "/srv/dc/data/t398-ready-v1",
                     "Source": "/var/lib/docker/volumes/t398-ready-v1/_data"},
                ],
            }
            old = role_layout(inspected, "order-b",
                              require_common_jar=False, require_running=False)
            self.assertEqual(
                "/var/lib/docker/volumes/t398-ready-v1/_data/"
                "OrderSvr/OrderSvrB",
                old["physical_root"])
            with self.assertRaisesRegex(ValueError, "NODE_NOT_RUNNING"):
                role_layout(inspected, "order-b",
                            require_common_jar=False, require_running=True)


if __name__ == "__main__":
    unittest.main()
