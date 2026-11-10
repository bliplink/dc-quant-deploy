import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recovery.build_structural_event_dataset import main


class StructuralEventDatasetContractTest(unittest.TestCase):
    def fixture(self, root, purpose='training_only', digest=None):
        original, parent, output = root / 'original', root / 'parent', root / 'output'
        original.mkdir(); parent.mkdir()
        ready = json.dumps({'purpose': purpose, 'train_end_exclusive': '2024-12-15', 'files': {}}).encode()
        (original / 'READY.json').write_bytes(ready)
        (parent / 'training-manifest.json').write_text(json.dumps({
            'ready_sha256': hashlib.sha256(ready).hexdigest()}), encoding='utf-8')
        (parent / 'frozen-models.json').write_bytes(b'{}')
        (parent / 'TRAINING_COMPLETE.json').write_text(json.dumps({
            'frozen_models_sha256': digest or hashlib.sha256(b'{}').hexdigest()}), encoding='utf-8')
        return ['builder', '--input-dir', str(original), '--parent-model-dir', str(parent), '--output-dir', str(output)], output

    def test_financial_input_cannot_be_treated_as_training_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            args, output = self.fixture(Path(directory), purpose='financial_validation')
            with patch('sys.argv', args), self.assertRaisesRegex(ValueError, 'contract'):
                main()
            self.assertFalse(output.exists())

    def test_changed_parent_model_cannot_reuse_event_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            args, output = self.fixture(Path(directory), digest='corrupted')
            with patch('sys.argv', args), self.assertRaisesRegex(ValueError, 'contract'):
                main()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
