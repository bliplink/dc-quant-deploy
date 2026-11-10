import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from recovery.run_local_source_strategy_cycle import verify_resume_markers


class CycleResumeTest(unittest.TestCase):
    def fixture(self, root):
        (root / 'screen').mkdir()
        (root / 'source-contract').mkdir()
        (root / 'screen/campaign.json').write_text('{}', encoding='utf-8')
        digest = hashlib.sha256(b'{}').hexdigest()
        self.write(root / 'screen/SCREEN_COMPLETE.json', {
            'manifest_sha256': digest, 'holdout_withheld': True, 'production_write': False})
        self.write(root / 'source-contract/SOURCE_CONTRACT_COMPLETE.json', {
            'campaign_sha256': digest, 'production_write': False})

    @staticmethod
    def write(path, data):
        path.write_text(json.dumps(data), encoding='utf-8')

    def test_formal_resume_requires_frozen_screen_and_withheld_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            verify_resume_markers(root, 'local_formal_holdout')
            marker = root / 'screen/SCREEN_COMPLETE.json'
            original = json.loads(marker.read_text(encoding='utf-8'))
            for key, value in [('manifest_sha256', 'changed'), ('holdout_withheld', False),
                               ('production_write', True)]:
                self.write(marker, {**original, key: value})
                with self.assertRaises(ValueError):
                    verify_resume_markers(root, 'local_formal_holdout')
            self.write(marker, original)
            (root / 'screen/campaign.json').write_text('{"changed":true}', encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_resume_markers(root, 'local_formal_holdout')

    def test_server_resume_requires_formal_result_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'formal').mkdir()
            with self.assertRaises(FileNotFoundError):
                verify_resume_markers(root, 'server_import_backtest_audit')
            (root / 'formal/manifest.json').write_text('{}', encoding='utf-8')
            self.write(root / 'formal/results.json', [])
            finished = {'manifest_sha256': hashlib.sha256(b'{}').hexdigest(),
                        'completed': 0, 'production_write': False}
            self.write(root / 'formal/FORMAL_COMPLETE.json', finished)
            verify_resume_markers(root, 'server_import_backtest_audit')
            self.write(root / 'formal/FORMAL_COMPLETE.json', {**finished, 'completed': 1})
            with self.assertRaises(ValueError):
                verify_resume_markers(root, 'server_import_backtest_audit')


if __name__ == '__main__':
    unittest.main()
