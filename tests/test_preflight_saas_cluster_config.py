#!/usr/bin/env python3
"""Regression tests for config-only fail-closed deploy preflight."""
import tempfile
import unittest
from pathlib import Path
from preflight_saas_cluster_config import check_static, read_properties


def settings(ab):
    env = {"ZOOKEEPER_PORT": "42181", "GW_TCP_PORT": "43000",
           "GW_WEBSOCKET_PORT": "43001", "GW_HTTP_PORT": "43002",
           "PROJECTIONSVR_GW_PORT": "43042", "APSSVR_GW_PORT": "43035",
           "MDSVR_GW_PORT": "43028", "ORDERSVR_GW_PORT": "43036",
           "ORDERSVR_B_GW_PORT": "43041", "TRADESVR_GW_PORT": "43037",
           "TRADESVR_B_GW_PORT": "43046",
           "ORDER_CLUSTER_ENABLED": str(ab).lower(),
           "TRADE_CLUSTER_ENABLED": str(ab).lower()}
    cfg = {"REGISTER.Svr1.Host": "127.0.0.1:42181"}
    for s, a, b in (("OrderSvr", "43036", "43041"),
                    ("TradeSvr", "43037", "43046")):
        cfg["SERVER." + s + ".RegType"] = "0" if ab else "2"
        cfg["SERVER." + (s + "A" if ab else s) + ".Host"] = "127.0.0.1:" + a
        cfg["SERVER." + (s + "A" if ab else s) + ".RegType"] = "2"
        if ab:
            cfg["SERVER." + s + "B.Host"] = "127.0.0.1:" + b
            cfg["SERVER." + s + "B.RegType"] = "2"
            cfg["LBConfig." + s] = "Partition"
            cfg["Cluster." + s + ".Enabled"] = "true"
    return env, cfg


class PreflightRegression(unittest.TestCase):
    def test_single_and_ab_good(self):
        for mode in (True, False):
            self.assertEqual([], check_static(*settings(mode)))

    def test_missing_b_node_rejected_before_startup(self):
        env, cfg = settings(True)
        del cfg["SERVER.OrderSvrB.Host"]
        self.assertIn("GATEWAY_NODE_B_MISSING_OR_WRONG:OrderSvr",
                      check_static(env, cfg))

    def test_single_mode_given_to_ab_refused(self):
        env, cfg = settings(False)
        env["ORDER_CLUSTER_ENABLED"] = "true"
        self.assertIn("GATEWAY_GROUP_MODE_MISMATCH:OrderSvr",
                      check_static(env, cfg))

    def test_zk_host_mismatch_and_port_collision(self):
        env, cfg = settings(True)
        cfg["REGISTER.Svr1.Host"] = "127.0.0.1:32181"
        env["ORDERSVR_B_GW_PORT"] = env["ORDERSVR_GW_PORT"]
        errors = check_static(env, cfg)
        self.assertIn("ZK_HOST_MISMATCH", errors)
        self.assertTrue(any(x.startswith("PORT_COLLISION:") for x in errors))

    def test_runtime_namespace_mismatch(self):
        env, cfg = settings(True)
        with tempfile.TemporaryDirectory() as root:
            for service in ("order", "trade"):
                for node in "AB":
                    f = Path(root) / "config-hostready" / service / node / "application.properties"
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(
                        f"{service}.common.control.zkHosts=127.0.0.1:42181\n"
                        f"{service}.common.nodeRuntime.freshE1.namespace=/otc/test/{service}\n"
                        f"{service}.common.nodeRuntime.bindPort={47000 + len(node) + (0 if service == 'order' else 10) + (0 if node == 'A' else 1)}\n")
            self.assertEqual([], check_static(env, cfg, root))
            collision = (Path(root) / "config-hostready" / "order" / "B" /
                         "application.properties")
            collision.write_text(collision.read_text().replace(
                "order.common.nodeRuntime.bindPort=47002",
                "order.common.nodeRuntime.bindPort=47001"))
            self.assertTrue(any(x.startswith("REPLICATION_PORT_COLLISION:")
                                for x in check_static(env, cfg, root)))
            f = Path(root) / "config-hostready" / "trade" / "B" / "application.properties"
            f.write_text("trade.common.control.zkHosts=t84-old:2181\n"
                         "trade.common.nodeRuntime.freshE1.namespace=/otc/test/other\n"
                         "trade.common.nodeRuntime.bindPort=47999\n")
            problems = check_static(env, cfg, root)
            self.assertIn("STALE_RUNTIME_ZK:tradeB", problems)
            self.assertIn("INVALID_COMMON_NAMESPACE:tradeB", problems)
            self.assertIn("AB_NAMESPACE_MISMATCH:trade", problems)

    def test_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ATSConfig.ini"
            p.write_text("SERVER.OrderSvr.Host=x\nSERVER.OrderSvr.Host=y\n")
            with self.assertRaisesRegex(ValueError, "DUPLICATE_CONFIG_KEY"):
                read_properties(p)


if __name__ == "__main__":
    unittest.main()