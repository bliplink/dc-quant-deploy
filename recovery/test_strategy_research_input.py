"""Fail-closed checks for local research inputs."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from recovery.convert_research_bars_for_scene_snapshot import convert
from recovery.export_strategy_research_data import assert_unique_bar_times as check_export
from recovery.run_local_strategy_validation import (
    assert_research_protocol,
    assert_scene_coverage,
    assert_unique_bar_times as check_validation,
)
from recovery.local_strategy_backtest import verify_local_research_input


class UniqueBarTimesTest(unittest.TestCase):
    def test_local_formal_replay_requires_ready_and_exact_hashes(self):
        protocol = Path(__file__).with_name('strategy_research_older_protocol_20261016.json')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {}
            for suffix, field in (('-15m.tsv', 'bars_sha256'),
                                  ('-scenes.tsv', 'scenes_sha256')):
                path = root / ('SOLUSDT' + suffix)
                path.write_text('fixture\n', encoding='utf-8')
                files[field] = hashlib.sha256(path.read_bytes()).hexdigest()
            ready = {'begin': '2024-12-15', 'end': '2025-10-12',
                     'model': 'gpt-5.6-sol', 'clock': 'UTC',
                     'files': {'SOLUSDT': files}}
            (root / 'READY.json').write_text(json.dumps(ready), encoding='utf-8')
            item = {'symbol': 'SOLUSDT', 'text': '15m'}
            self.assertEqual(files, verify_local_research_input(
                root, protocol, item, '2024-12-15', '2025-10-12'))
            with self.assertRaisesRegex(ValueError, 'contract mismatch'):
                verify_local_research_input(root, protocol, item,
                                            '2024-12-15', '2025-10-11')
            (root / 'SOLUSDT-scenes.tsv').write_text('changed\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                verify_local_research_input(root, protocol, item,
                                            '2024-12-15', '2025-10-12')

    def test_older_protocol_withholds_holdout_and_checks_ready_hashes(self):
        protocol = Path(__file__).with_name('strategy_research_older_protocol_20261016.json')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {}
            for suffix, field in (('-15m.tsv', 'bars_sha256'),
                                  ('-scenes.tsv', 'scenes_sha256')):
                path = root / ('SOLUSDT' + suffix)
                path.write_text('test data\n', encoding='utf-8')
                files[field] = hashlib.sha256(path.read_bytes()).hexdigest()
            ready = {'begin': '2024-12-15', 'end': '2025-10-12',
                     'model': 'gpt-5.6-sol', 'clock': 'UTC',
                     'files': {'SOLUSDT': files}}
            (root / 'READY.json').write_text(json.dumps(ready), encoding='utf-8')
            self.assertEqual(len(assert_research_protocol(
                protocol, root, '2024-12-15', '2025-08-11', ['SOLUSDT'])), 64)
            with self.assertRaisesRegex(ValueError, 'holdout'):
                assert_research_protocol(protocol, root, '2024-12-15',
                                         '2025-08-12', ['SOLUSDT'])
            (root / 'SOLUSDT-scenes.tsv').write_text('changed\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                assert_research_protocol(protocol, root, '2024-12-15',
                                         '2025-08-11', ['SOLUSDT'])

    def check_both(self, content, should_pass):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SOLUSDT-15m.tsv'
            path.write_bytes(content)
            for check in (check_export, check_validation):
                if should_pass:
                    check(path)
                else:
                    with self.assertRaisesRegex(ValueError, 'duplicate or unordered startTime'):
                        check(path)

    def test_unique_ascending_bars(self):
        self.check_both(b'2026-08-17 12:30:00\t75\n2026-08-17 12:45:00\t76\n', True)

    def test_duplicate_bar_is_rejected(self):
        self.check_both(b'2026-08-17 12:45:00\t75\n2026-08-17 12:45:00\t76\n', False)

    def test_descending_bar_is_rejected(self):
        self.check_both(b'2026-08-17 12:45:00\t75\n2026-08-17 12:30:00\t76\n', False)

    def test_scene_window_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SOLUSDT-scenes.tsv'
            path.write_text('2025-10-13 00:00:00\trange\n2026-10-13 12:00:00\ttrend\n',
                            encoding='utf-8')
            assert_scene_coverage(path, '2025-10-13', '2026-10-13')

    def test_missing_early_scenes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SOLUSDT-scenes.tsv'
            path.write_text('2025-08-12 00:00:00\trange\n2025-10-12 12:00:00\ttrend\n',
                            encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'does not cover'):
                assert_scene_coverage(path, '2024-08-12', '2025-10-12')

    def test_scene_snapshot_converter_uses_utc_bar_end(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'BTCUSDT-15m.tsv'
            target = Path(directory) / 'BTCUSDT_15M.jsonl'
            source.write_text('2025-01-15 00:00:00\t1\t2\t0.5\t1.5\t100\n', encoding='utf-8')
            self.assertEqual(convert(source, target), 1)
            import json
            row = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(row['starttimems'], 1736899200000)
            self.assertEqual(row['endtimems'] - row['starttimems'], 15 * 60 * 1000)


if __name__ == '__main__':
    unittest.main()
