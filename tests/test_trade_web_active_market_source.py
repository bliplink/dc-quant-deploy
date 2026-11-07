"""T543: one-click must build latest actual Web, not pre-Kline-fix branch."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class TradeWebSourceTests(unittest.TestCase):
    def test_one_click_builds_latest_real_web_branch(self):
        script=(ROOT/'build-saas-images.sh').read_text()
        self.assertIn('sync_repo trade-web https://github.com/bliplink/dc-trade-web.git "${TRADE_WEB_SOURCE_BRANCH:-saas-crypto-latest}"',script)
        self.assertNotIn('sync_repo trade-web https://github.com/bliplink/dc-trade-web.git saas-crypto\n',script)

    def test_web_branch_config_separate_from_image_tag(self):
        env=(ROOT/'.env.example').read_text()
        self.assertIn('TRADE_WEB_SOURCE_BRANCH=saas-crypto-latest',env)
        self.assertIn('TRADE_WEB_TAG=saas-crypto',env)

if __name__=='__main__':
    unittest.main()