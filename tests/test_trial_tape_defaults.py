"""Guard fresh SaaS install against silently disabling trial tape."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class TrialTapeDefaultsTest(unittest.TestCase):
    def test_default_is_on_for_both_generate_env_and_compose(self):
        deploy=(ROOT/'deploy-saas.sh').read_text()
        self.assertIn('TRIAL_LIQUIDITY_TAPE_ENABLED=true',deploy)
        self.assertNotIn('TRIAL_LIQUIDITY_TAPE_ENABLED=false\\n',deploy)
        self.assertIn('TRIAL_LIQUIDITY_TAPE_ENABLED=true',deploy)
        self.assertIn('TRIAL_LIQUIDITY_TAPE_ENABLED: ${TRIAL_LIQUIDITY_TAPE_ENABLED:-true}',(ROOT/'compose.yaml').read_text())
    def test_operator_override_is_preserved(self):
        deploy=(ROOT/'deploy-saas.sh').read_text()
        k="if ! grep -q '^TRIAL_LIQUIDITY_TAPE_ENABLED=' \"${ENV_FILE}\"; then"
        self.assertIn(k,deploy)
if __name__=='__main__':unittest.main()
