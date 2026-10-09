"""Offline GW partition request validation with no secrets or network."""
import importlib.util
import json
from pathlib import Path
import unittest

MODULE = Path(__file__).with_name("gw-partition-route.py")
spec = importlib.util.spec_from_file_location("gw_partition_route", MODULE)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def envelope(service="OrderSvr", content=None):
    return {"serverName": service, "method": "placeOrder", "content": content if content is not None else {
        "SecurityID": "BTCUSDT", "MarketIndicator": "4", "ClOrdID": "offline",
    }}


class GwPartitionRouteTests(unittest.TestCase):
    def test_trader_order_receives_correct_route(self):
        req = route.apply_route(envelope(), "ABC123")
        self.assertEqual(req["key"], "ABC123" + chr(31) + "4" + chr(31) + "BTCUSDT")
        self.assertEqual(req["content"]["ClOrdID"], "offline")

    def test_broker_explicit_location_and_user_are_preserved(self):
        req = envelope(content={"Location":"ABC123", "UserID":"customer-A",
                                "SecurityID":"BTCUSDT", "MarketIndicator":"4"})
        result = route.apply_route(req, "DIFFERENT")
        self.assertEqual(result["key"], "ABC123" + chr(31) + "4" + chr(31) + "BTCUSDT")
        self.assertEqual(result["content"]["UserID"], "customer-A")

    def test_market_data_content_uses_case_sensitive_security_id(self):
        req = envelope("MDSvr", {"location":"ABC123", "securityID":"BTCUSDT"})
        self.assertEqual(route.apply_route(req, "FALLBACK")["key"],
                         "ABC123" + chr(31) + "4" + chr(31) + "BTCUSDT")

    def test_order_query_and_cancel_both_route(self):
        for name, field in (("queryOpenOrder","securityid"), ("cancelOrder","SecurityID")):
            req = envelope(content={field:"BTCUSDT", "MarketIndicator":"4"})
            req["method"] = name
            self.assertEqual(route.apply_route(req, "ABC123")["key"].count(chr(31)), 2)

    def test_preexisting_matching_key_is_preserved(self):
        req = envelope()
        req["key"] = "ABC123" + chr(31) + "4" + chr(31) + "BTCUSDT"
        self.assertEqual(route.apply_route(req, "ABC123")["key"], req["key"])

    def test_reject_wrong_key_instead_of_sending(self):
        req = envelope()
        req["key"] = "FOREIGN" + chr(31) + "4" + chr(31) + "BTCUSDT"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            route.apply_route(req, "ABC123")

    def test_double_escaped_key_is_invalid(self):
        req = envelope()
        req["key"] = "ABC123" + r"\u001f" + "4" + r"\u001f" + "BTCUSDT"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            route.apply_route(req, "ABC123")

    def test_reject_missing_symbol_and_malformed_location(self):
        with self.assertRaisesRegex(ValueError, "requires SecurityID"):
            route.apply_route(envelope(content={"location":"ABC123"}), "ABC123")
        with self.assertRaisesRegex(ValueError, "invalid GW partition location"):
            route.apply_route(envelope(), "../FOREIGN")

    def test_non_partitioned_services_remain_unmodified(self):
        req = envelope("LoginSvr", {"api_key":"placeholder"})
        self.assertIs(route.apply_route(req, "ABC123"), req)
        self.assertNotIn("key", req)

    def test_cli_json_serializes_actual_unit_separator(self):
        req = route.apply_route(envelope(), "ABC123")
        wire = json.dumps(req, ensure_ascii=True)
        self.assertIn(r"\u001f", wire)
        self.assertEqual(json.loads(wire)["key"].count(chr(31)), 2)


if __name__ == "__main__":
    unittest.main()
