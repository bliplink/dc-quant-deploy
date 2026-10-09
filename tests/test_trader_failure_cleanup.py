"""Offline failure-cleanup tests, with mocked GW; no live orders or secrets."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SHELL = Path(__file__).with_name("run-tenant-lifecycle-e2e-host.sh")


def fixture(order_id="ORDER-123", clord="TRADER_WRITE_DEMO01"):
    return {"code": 0, "data": [{"ClOrdID": clord, "OrderID": order_id}]}


class TraderCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = SHELL.read_text()
        match = re.search(
            r"(?ms)^cleanup_pending_trader_order\(\) \{\n.*?^\}",
            text,
        )
        assert match, "Failure cleanup helper is missing"
        cls.source = match.group(0)

    def run_cleanup(self, payload, token="test-only-token", clord="TRADER_WRITE_DEMO01"):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "requests.jsonl"
            program = self.source + """
set -u
E2E_SUFFIX=DEMO01
trader_new_clordid="$MOCK_CLORD"
trader_write_token="$MOCK_TOKEN"
log() { printf '[mock-e2e] %s\\n' "$*" >&2; }
code_of() { python3 -c 'import json,sys;print(json.loads(sys.argv[1]).get("code",""))' "$1"; }
api_call() {
  local payload="$1"
  printf '%s\\n' "$payload" >> "$MOCK_CAPTURE"
  if [[ "$payload" == *'"method":"queryOpenOrder"'* ]]; then
    if grep -q '"method":"cancelOrder"' "$MOCK_CAPTURE"; then
      printf '{"code":0,"data":[]}'
    else
      printf '%s' "$MOCK_OPEN"
    fi
  elif [[ "$payload" == *'"method":"cancelOrder"'* ]]; then
    printf '{"code":0}'
  else
    return 1
  fi
}
cleanup_pending_trader_order
"""
            import os
            env = dict(os.environ)
            env.update({
                "MOCK_CLORD": clord, "MOCK_TOKEN": token,
                "MOCK_OPEN": json.dumps(payload),
                "MOCK_CAPTURE": str(capture),
            })
            result = subprocess.run(["bash", "-c", program], env=env,
                                    text=True, capture_output=True, timeout=6)
            calls = [
                json.loads(row) for row in capture.read_text().splitlines()
            ] if capture.exists() else []
            return result, calls

    def test_matching_open_order_is_cancelled_using_server_order_id(self):
        result, calls = self.run_cleanup(fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["method"] for call in calls],
                         ["queryOpenOrder", "cancelOrder", "queryOpenOrder"])
        self.assertEqual(calls[1]["content"]["OrderID"], "ORDER-123")
        self.assertIn("no longer appears", result.stderr)

    def test_unrelated_open_order_must_never_be_cancelled(self):
        result, calls = self.run_cleanup(fixture(clord="OTHER_CUSTOMER_ORDER"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c["method"] for c in calls], ["queryOpenOrder"])
        self.assertIn("no open test order matched", result.stderr)

    def test_ambiguous_or_invalid_snapshot_fails_without_cancelling(self):
        for rows in ({"bad": "shape"}, [
            {"ClOrdID": "TRADER_WRITE_DEMO01", "OrderID": "ORDER-1"},
            {"ClOrdID": "TRADER_WRITE_DEMO01", "OrderID": "ORDER-2"},
        ]):
            result, calls = self.run_cleanup({"code": 0, "data": rows})
            self.assertEqual(result.returncode, 0)
            self.assertEqual([c["method"] for c in calls], ["queryOpenOrder"])
            self.assertIn("manual reconciliation required", result.stderr)

    def test_no_active_trader_session_is_network_free(self):
        result, calls = self.run_cleanup(fixture(), token="")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_missing_clordid_is_network_free(self):
        result, calls = self.run_cleanup(fixture(), clord="")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
