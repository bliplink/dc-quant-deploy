"""Offline guard for TradeSvr tenant partition routing in public examples."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TradeAccountRoutingTests(unittest.TestCase):
    def test_live_e2e_balance_requests_include_tenant_route_key(self):
        src = (ROOT / "tests/run-tenant-lifecycle-e2e-host.sh").read_text()
        for label in ("trader_balance_payload", "tenant_api_balance_payload"):
            line = next(line for line in src.splitlines() if line.startswith(label + "="))
            self.assertIn('"key":"%s"', line, label)
            self.assertIn('"${E2E_LOCATION_A}"', line, label)

    def test_public_balance_and_position_examples_route_by_tenant(self):
        src = (ROOT / "docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md").read_text()
        for method in ("queryAccountBalance", "queryTradePosition"):
            self.assertIn('"method": "' + method + '",\n  "key": "YOUR_TENANT_LOCATION"', src)
        self.assertIn("实际账户身份与权限始终来自", src)

if __name__ == "__main__":
    unittest.main()
