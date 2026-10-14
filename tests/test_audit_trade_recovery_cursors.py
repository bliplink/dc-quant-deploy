import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / 'scripts' / 'audit-trade-recovery-cursors.py'
spec = importlib.util.spec_from_file_location('trade_cursor_audit', str(SOURCE))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TradeCursorAuditTest(unittest.TestCase):
    def test_detects_real_snapshot_ahead_and_keeps_only_non_sensitive_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / 'data/TradeSvrB/snapshot/P071/latest.json'
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({'snapshotSeq': 312034,
                                            'committedStateSeq': 312033,
                                            'committedStateEpoch': 1, 'epoch': 1,
                                            'balances': [{'userID': 'private'}]}))
            baseline = root / 'data/TradeSvrB/journal/P071/baseline.properties'
            baseline.parent.mkdir(parents=True)
            baseline.write_text('baselineSeq=309368\ncommitMarkerSeq=309368\n')
            log = root / 'log/TradeSvrB.log'
            log.parent.mkdir(parents=True)
            log.write_text('TradeSvr snapshot is ahead of local journal partition=P071, '
                           'snapshotSeq=312034, localLastSeq=309369\n')
            result = mod.audit(root / 'data', root / 'log', ('TradeSvrB',))
            self.assertEqual('BLOCKED', result['decision'])
            self.assertEqual(1, result['unresolvedCount'])
            row = result['nodes']['TradeSvrB']['details'][0]
            self.assertEqual(309368, row['journalBaseline']['baselineSeq'])
            self.assertEqual(312034, row['currentSnapshotMetadata']['snapshotSeq'])
            self.assertNotIn('private', json.dumps(result))
    def test_stale_error_after_bounded_snapshot_replacement_is_not_counted_as_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / 'data/TradeSvrA/snapshot/P042/latest.json'
            metadata.parent.mkdir(parents=True)
            metadata.write_text('{"snapshotSeq":20,"committedStateSeq":19,'
                                '"committedStateEpoch":1,"epoch":1}')
            log = root / 'log/TradeSvrA.log'
            log.parent.mkdir(parents=True)
            log.write_text('TradeSvr snapshot is ahead of local journal partition=P042, '
                           'snapshotSeq=25, localLastSeq=22\n')
            result = mod.audit(root / 'data', root / 'log', ('TradeSvrA',))
            self.assertEqual(0, result['unresolvedCount'])
            self.assertEqual('NO_GAP_IN_LOG_TAIL_NOT_A_PROOF', result['decision'])
    def test_missing_data_never_infers_safe_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / 'log/TradeSvrB.log'
            log.parent.mkdir(parents=True)
            log.write_text('TradeSvr snapshot is ahead of local journal partition=P071, '
                           'snapshotSeq=12, localLastSeq=10\n')
            result = mod.audit(root / 'data', root / 'log', ('TradeSvrB',))
            self.assertEqual('BLOCKED', result['decision'])


if __name__ == '__main__':
    unittest.main()
