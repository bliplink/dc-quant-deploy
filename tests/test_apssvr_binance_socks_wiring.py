#!/usr/bin/env python3
"""T540: ensure Mac VPN SOCKS5 is scoped to Binance Futures in Compose."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
ENV = (ROOT / ".env.example").read_text(encoding="utf-8")


class ApsBinanceSocksWiringTests(unittest.TestCase):
    def test_apssvr_proxy_variables_are_explicit(self):
        aps = COMPOSE.split("\n  apssvr:\n", 1)[1].split("\n  ordersvr:\n", 1)[0]
        self.assertIn("APSSVR_BINANCE_SOCKS_HOST: ${APSSVR_BINANCE_SOCKS_HOST:-}", aps)
        self.assertIn("APSSVR_BINANCE_SOCKS_PORT: ${APSSVR_BINANCE_SOCKS_PORT:-}", aps)

    def test_mac_host_vpn_reference_is_opt_in(self):
        self.assertIn("APSSVR_BINANCE_SOCKS_HOST=", ENV)
        self.assertIn("APSSVR_BINANCE_SOCKS_PORT=", ENV)
        self.assertIn("host.lima.internal", ENV)
        self.assertIn("10808", ENV)

    def test_no_global_http_proxy_injection_into_cluster(self):
        gateway = COMPOSE.split("\n  gateway:\n", 1)[1].split("\n  loginsvr:\n", 1)[0]
        self.assertNotIn("APSSVR_BINANCE_SOCKS_HOST", gateway)
        self.assertNotIn("ALL_PROXY:", gateway)
        self.assertNotIn("HTTPS_PROXY:", gateway)

    def test_apssvr_still_keeps_java_options_separate(self):
        aps = COMPOSE.split("\n  apssvr:\n", 1)[1].split("\n  ordersvr:\n", 1)[0]
        self.assertIn("JAVA_TOOL_OPTIONS: ${APSSVR_EXTRA_JAVA_OPTS:-}", aps)
        self.assertNotIn("http.proxyHost=host.lima.internal", aps)
        self.assertNotIn("https.proxyHost=host.lima.internal", aps)


if __name__ == "__main__":
    unittest.main()