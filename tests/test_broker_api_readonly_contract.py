"""Strictly offline tests for the no-writes Broker API smoke client."""
import importlib.util
from pathlib import Path
import unittest

F = Path(__file__).with_name("broker-api-readonly-acceptance.py")
spec = importlib.util.spec_from_file_location("readonly_broker", F)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ReadonlyBrokerContract(unittest.TestCase):
    def test_allowlisted_reads_and_signing_transport_only(self):
        self.assertEqual(m.ALLOWED_METHODS, {
            ("LoginSvr", "apiKeyLogin"),
            ("MDSvr", "queryPublicMarket"),
            ("TradeSvr", "queryAccountBalance"),
            ("AdminSvr", "queryOrder"),
            ("AdminSvr", "queryExecOrder"),
            ("AdminSvr", "tenantTradeAdmin"),
            ("LoginSvr", "tenantApiKeyAdmin"),
        })

    def test_refuses_mutating_calls(self):
        for name in ("placeOrder", "cancelOrder", "cashIn", "cashOut", "tenantUserAdmin",
                     "updateApiKey", "deleteApiKey"):
            with self.assertRaises(m.ContractError):
                m.body_bytes("TradeSvr", name, {})
        with self.assertRaises(m.ContractError):
            m.body_bytes("LoginSvr", "tenantApiKeyAdmin", {"action": "CREATE"})

    def test_signed_bytes_match_hmac(self):
        b = m.body_bytes("LoginSvr", "apiKeyLogin", {"location":"ABC123","api_key":"TEST"})
        import hashlib,hmac
        expected = hmac.new(b"secret", b+b"1700000000", hashlib.sha256).hexdigest()
        self.assertEqual(m.sign("secret", b, "1700000000"), expected)

    def test_gateway_route_uses_single_api_login(self):
        self.assertEqual(m.body_bytes("LoginSvr", "apiKeyLogin", {}),
                         b'{"serverName":"LoginSvr","method":"apiKeyLogin","content":{}}')

if __name__ == "__main__":
    unittest.main()
