"""Offline evidence contract for the Broker integration harness.

Never connects to a gateway, uses test credentials or reads a database.
Verifies that the shell's Python summary gate rejects stale/foreign runs.
"""
import json
import re
import subprocess
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("run-broker-api-e2e-host.sh")


class BrokerEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = SOURCE.read_text()
        marker = 'python3 - "${summary}" "${BROKER_E2E_LOCATION}"'
        start = text.find(marker)
        assert start >= 0, "Broker summary verification was removed"
        snippet = text[start:]
        cls.validation = snippet.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        cls.host_code = text

    def fixture(self):
        return {
            "result": "PASS", "location": "AB1234",
            "makerCustomerId": "maker-001", "takerCustomerId": "taker-002",
            "makerClOrdId": "RBmaker20261009-M20261009T180",
            "takerClOrdId": "RBtaker20261009-T20261009T180",
            "makerExecId": "ex-maker-001", "takerExecId": "ex-taker-002",
            "foreignCustomerRejected": True, "reconnected": True,
        }

    def check(self, data, location="AB1234", maker="maker-001", taker="taker-002", run="20261009T180000Z"):
        return subprocess.run([
            "python3", "-", json.dumps(data), location, maker, taker, run,
        ], input=self.validation, capture_output=True, text=True, timeout=5)

    def test_matching_run_passes_offline(self):
        self.assertEqual(self.check(self.fixture()).returncode, 0)

    def test_wrong_location_denied(self):
        bad = self.fixture()
        bad["location"] = "BAD000"
        self.assertNotEqual(self.check(bad).returncode, 0)

    def test_wrong_customer_denied(self):
        bad = self.fixture()
        bad["takerCustomerId"] = "other-tenant-customer"
        self.assertNotEqual(self.check(bad).returncode, 0)

    def test_previous_run_id_denied(self):
        bad = self.fixture()
        bad["makerClOrdId"] = "RBmakerOLD-MOLD"
        self.assertNotEqual(self.check(bad).returncode, 0)

    def test_missing_execution_id_denied(self):
        bad = self.fixture()
        bad["makerExecId"] = None
        self.assertNotEqual(self.check(bad).returncode, 0)

    def test_db_checks_use_exact_executions_and_cash_once(self):
        text = self.host_code
        self.assertIn("e.exec_id='${maker_exec_id}'", text)
        self.assertIn("e.exec_id='${taker_exec_id}'", text)
        self.assertIn("rows[i] == 1", text)
        self.assertNotIn("(( rows[i] >= 1 ))", text)


if __name__ == "__main__":
    unittest.main()
