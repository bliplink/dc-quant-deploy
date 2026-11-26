import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simulation_tenants


class TenantProvisioningRetry(unittest.TestCase):
    def test_interrupted_signup_reuses_all_request_identities_and_passwords(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "sim-demo-20261127-120000"
            directory.mkdir()
            accepted = {}
            requests = []
            interrupt = True

            def submit(application):
                nonlocal interrupt
                key = application["request_id"]
                location, password = accepted.setdefault(key, (f"A{len(accepted):05}", application["admin_password"]))
                self.assertEqual(password, application["admin_password"])
                requests.append(key)
                if len(requests) == 3 and interrupt:
                    interrupt = False
                    raise TimeoutError("lost response after approval")
                return {"approved_location": location, "status": "APPROVED"}

            with patch.object(simulation_tenants.subprocess, "check_output", return_value=directory.name), \
                 patch.object(simulation_tenants, "submit", side_effect=submit), \
                 patch.object(simulation_tenants, "funded", return_value=10):
                with self.assertRaises(TimeoutError):
                    simulation_tenants.enroll(directory)
                locations = simulation_tenants.enroll(directory)
            self.assertEqual(10, len(set(locations)))
            self.assertEqual(10, len(accepted))
            self.assertEqual(requests[:3], requests[3:6])
            self.assertEqual(0o600, os.stat(directory / "demo-tenant-applications.json").st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
