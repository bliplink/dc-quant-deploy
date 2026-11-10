import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recovery import validate_local_catalog_sources as validator


class SourceContractPreflightTest(unittest.TestCase):
    def execute(self, parity_code):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / 'campaign'
            campaign.mkdir()
            (campaign / 'campaign.json').write_text(json.dumps({
                'catalog': [{'hypothesis': 'frozen'}]}), encoding='utf-8')
            source = root / 'frozen'
            source.mkdir()
            (source / 'GeneratedStrategy.java').write_text('class Frozen {}', encoding='utf-8')
            jar = root / 'strategy.jar'
            jar.write_bytes(b'test artifact')
            args = ['validator', '--campaign-dir', str(campaign), '--indsvr-repo', str(root),
                    '--sim-repo', str(root), '--output-dir', str(root / 'output'), '--input-dir', str(root)]
            responses = [subprocess.CompletedProcess([], 0, stdout='valid', stderr=''),
                         subprocess.CompletedProcess([], parity_code)]
            with patch('sys.argv', args), patch.object(validator, 'export_candidate', return_value=(source, 'candidate')), \
                 patch.object(validator, 'compile_source', return_value=(jar, 'Frozen', source / 'GeneratedStrategy.java')), \
                 patch.object(validator, 'java_classpath', return_value='fake-classpath'), \
                 patch.object(validator.subprocess, 'run', side_effect=responses) as run:
                if parity_code:
                    with self.assertRaisesRegex(ValueError, 'bytecode/source signal mismatch'):
                        validator.main()
                    self.assertFalse((root / 'output' / 'SOURCE_CONTRACT_COMPLETE.json').exists())
                else:
                    validator.main()
                    self.assertTrue((root / 'output' / 'SOURCE_CONTRACT_COMPLETE.json').exists())
                command = run.call_args_list[1].args[0]
                self.assertIn('2025-04-14', command)
                self.assertIn('2025-05-13', command)
                self.assertIn('BTCUSDT', command)

    def test_matching_signals_allow_source_contract_completion(self):
        self.execute(0)

    def test_stale_bytecode_is_blocked_before_financial_screening(self):
        self.execute(1)


if __name__ == '__main__':
    unittest.main()
