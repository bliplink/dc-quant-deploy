from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recovery.run_ohlcv_profile_proxy_batch import frozen_queue, require_parent_complete, run_case, strict_primary
from recovery import test_ohlcv_profile_proxy as export_fixtures
from recovery.verify_fit_only_risk_contract import sha


class OhlcvProfileBatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        export_fixtures.OhlcvProfileProxyExportTest.setUpClass()
        cls.native = export_fixtures.OhlcvProfileProxyExportTest.native

    def primary(self, forward=20):
        return dict(primaryQualified=True, qualificationReason='qualified', selectedParameters={}, parameterGridSearch=False,
            result=dict(executionModelVersion='v4_non_overlapping_walk_forward', oosPass=1, tradeCount=30,
                profitFactor=1.5, maxDrawdownPct=.05, feeAdjustedValidatePnl=50,
                feeAdjustedForwardPnl=forward, totalPnl=100, minForwardContribution=0))

    def test_entire_scope_queue_is_deterministic_unique_and_one_mechanism(self):
        symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT']
        rows = frozen_queue(self.native, symbols)
        self.assertEqual(rows, frozen_queue(self.native, list(reversed(symbols))))
        self.assertEqual(200, len({row['strategy'] for row in rows}))
        self.assertEqual({'ohlcv_distribution_auction'}, {row['mechanism_group'] for row in rows})
        with self.assertRaises(ValueError):
            frozen_queue(self.native, symbols[:-1] + [symbols[0]])

    def test_strict_policy_precedes_holdout_and_never_weakens_original_gate(self):
        self.assertFalse(strict_primary(self.primary(19.9), {})[0])
        self.assertTrue(strict_primary(self.primary(), {})[0])
        self.assertFalse(strict_primary(self.primary(), {'minForwardContribution': .30})[0])
        primary = self.primary(); primary['primaryQualified'] = False
        self.assertFalse(strict_primary(primary, {})[0])

    def test_parent_disappearance_incomplete_marker_and_failure_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {'queue': [{'strategy': 's' + str(i)} for i in range(400)]}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            parent = {'output_dir': str(root), 'manifest_sha256': sha(root / 'manifest.json')}
            with self.assertRaises(FileNotFoundError):
                require_parent_complete(parent)
            marker = dict(manifest_sha256=parent['manifest_sha256'], completed=400, production_write=False)
            (root / 'BATCH_COMPLETE.json').write_text(json.dumps(marker))
            require_parent_complete(parent)
            (root / 'BATCH_COMPLETE.json').write_text(json.dumps(dict(marker, completed=399)))
            with self.assertRaises(ValueError): require_parent_complete(parent)
            (root / 'BATCH_COMPLETE.json').write_text(json.dumps(marker))
            (root / 'FAILED.json').write_text('{}')
            with self.assertRaises(ValueError): require_parent_complete(parent)

    def test_partial_financial_directory_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'candidates/frozen').mkdir(parents=True)
            with patch('recovery.run_ohlcv_profile_proxy_batch.execute') as execute:
                with self.assertRaisesRegex(ValueError, 'partial attempt'):
                    run_case(Namespace(output_dir=root), {'strategy': 'frozen'}, 'manifest', {}, {}, '', '', {})
                execute.assert_not_called()

    def test_completed_failure_is_reused_and_mechanism_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'candidates/frozen').mkdir(parents=True)
            (root / 'candidates/frozen/checkpoint.json').write_text('{}')
            row = dict(strategy='frozen', symbol='BTCUSDT', scene='trend', hypothesis='fixed', family='family',
                       mechanism_group='ohlcv_distribution_auction', mode=0, side=1)
            record = dict(row, qualified=False)
            with patch('recovery.run_ohlcv_profile_proxy_batch.completed_case', return_value=record), \
                 patch('recovery.run_ohlcv_profile_proxy_batch.execute') as execute:
                self.assertEqual(record, run_case(Namespace(output_dir=root), row, 'hash', {}, {}, '', '', {}))
                with self.assertRaises(ValueError):
                    run_case(Namespace(output_dir=root), dict(row, mechanism_group='new_name'), 'hash', {}, {}, '', '', {})
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
