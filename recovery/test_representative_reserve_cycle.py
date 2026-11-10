import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from recovery.run_representative_reserve_cycle import require_parent_complete


class RepresentativeReserveCycleTest(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        digest = hashlib.sha256(b'{}').hexdigest()
        self.put(root, 'cycle-status.json', {'stage': 'cycle_complete', 'state': 'complete'})
        self.put(root, 'screen/campaign.json', {})
        self.put(root, 'screen/SCREEN_COMPLETE.json', {
            'manifest_sha256': digest, 'holdout_withheld': True, 'production_write': False})
        self.put(root, 'source-contract/SOURCE_CONTRACT_COMPLETE.json', {
            'campaign_sha256': digest, 'production_write': False})
        item = {'symbol': 'BTCUSDT', 'scene': 'range', 'hypothesis': 'fixed_entry'}
        self.put(root, 'screen/shortlist.json', [item])
        self.put(root, 'formal/manifest.json', {})
        self.put(root, 'formal/FORMAL_COMPLETE.json', {
            'manifest_sha256': digest, 'completed': 1, 'production_write': False})
        self.put(root, 'formal/results.json', [{**item, 'qualified': False}])
        status = {'completed': 1, 'total': 1, 'local_formal_qualified': 0, 'errors': []}
        self.put(root, 'formal/status.json', status)
        self.put(root, 'formal/cycle-summary.json', {'local_formal_status': status})
        return root

    @staticmethod
    def put(root, relative, value):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_complete_financial_failures_remain_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            require_parent_complete(self.fixture(directory))

    def test_parent_still_auditing_or_failed_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            for state in ('running', 'failed'):
                self.put(root, 'cycle-status.json', {'stage': 'server_import_backtest_audit', 'state': state})
                with self.assertRaises(ValueError):
                    require_parent_complete(root)

    def test_omitted_financial_failure_cannot_enter_reserve_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.put(root, 'formal/results.json', [])
            with self.assertRaises(ValueError):
                require_parent_complete(root)

    def test_result_identity_mismatch_and_stale_audit_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            self.put(root, 'formal/results.json', [{'symbol': 'ETHUSDT', 'scene': 'range', 'hypothesis': 'other'}])
            with self.assertRaises(ValueError):
                require_parent_complete(root)
            root = self.fixture(directory)
            self.put(root, 'formal/cycle-summary.json', {'local_formal_status': {'completed': 0}})
            with self.assertRaises(ValueError):
                require_parent_complete(root)


if __name__ == '__main__':
    unittest.main()
