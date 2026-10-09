"""Offline E2E harness test: diagnostics must never corrupt returned IDs.

Extracts only shell helper definitions. Mocks the gateway. No credentials,
Docker, network or running tenant endpoints.
"""
from pathlib import Path
import re
import subprocess
import unittest


SOURCE = Path(__file__).with_name("run-tenant-lifecycle-e2e-host.sh")
NAMES = (
    "log", "die", "json_eval", "code_of", "expect_ok",
    "submit_application", "register_trader",
)


class TenantShellIoTests(unittest.TestCase):
    def test_application_and_registration_return_clean_ids(self):
        source = SOURCE.read_text(encoding="utf-8")
        functions = []
        for name in NAMES:
            match = re.search(
                r"(?ms)^" + re.escape(name) + r"\(\) \{\n.*?^\}",
                source,
            )
            self.assertIsNotNone(match, name)
            functions.append(match.group(0))
        fixture = "\n\n".join(functions)
        test_program = fixture + """
set -euo pipefail
E2E_SUFFIX=OFFLINE
E2E_SHARED_USER=testuser
api_call() {
  local body="$1"
  if [[ "$body" == *tenantApplication* ]]; then
    printf '{"code":0,"data":{"application_id":"app-test-001"}}'
  elif [[ "$body" == *tenantUserRegistration* ]]; then
    printf '{"code":0,"data":{"user_id":"trader-test-002"}}'
  else
    printf '{"code":9000}'
  fi
}
app_id="$(submit_application ABC123 testing@example.invalid REQ-001)"
user_id="$(register_trader ABC123 not-a-real-password testing@example.invalid)"
[[ "$app_id" == app-test-001 ]]
[[ "$user_id" == trader-test-002 ]]
printf 'ID_OUTPUT_IS_CLEAN'
"""
        completed = subprocess.run(
            ["bash", "-c", test_program],
            check=False, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ID_OUTPUT_IS_CLEAN")
        self.assertIn("PASS: submit ABC123", completed.stderr)
        self.assertIn("PASS: register ABC123", completed.stderr)
        self.assertNotIn("not-a-real-password", completed.stderr)


if __name__ == "__main__":
    unittest.main()
