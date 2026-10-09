"""Offline preflight contract: immutable image, zero-network, no API Key args."""
from pathlib import Path
import unittest

ROOT = Path(__file__).parent
CHILD = ROOT / "run-broker-api-e2e-host.sh"
PREFLIGHT = ROOT / "check-broker-runner-host.sh"


class BrokerOfflinePreflightContract(unittest.TestCase):
    def test_no_secret_values_on_docker_command_line(self):
        text = CHILD.read_text()
        # The Docker CLI inherits only the named environment variables.
        # The sensitive values must not be expanded into argv or log output.
        self.assertIn('-e BROKER_E2E_API_KEY   -e BROKER_E2E_API_SECRET', text)
        self.assertNotIn('-e BROKER_E2E_API_KEY="${BROKER_E2E_API_KEY}"', text)
        self.assertNotIn('-e BROKER_E2E_API_SECRET="${BROKER_E2E_API_SECRET}"', text)
        self.assertIn("raw logs suppressed", text)

    def test_offline_preflight_fails_closed_before_no_network_smoke(self):
        text = PREFLIGHT.read_text()
        self.assertLess(text.index("broker-runner-image-review.py"), text.index("docker run"))
        self.assertIn("docker image inspect", text)
        self.assertIn("docker run --rm --network none", text)
        self.assertIn("BROKER_E2E_LOCATION is required", text)
        self.assertNotIn("BROKER_E2E_API_KEY", text)
        self.assertNotIn("BROKER_E2E_API_SECRET", text)
        self.assertNotIn("ENV_FILE", text)
        self.assertNotIn("--network host", text)


if __name__ == "__main__":
    unittest.main()
