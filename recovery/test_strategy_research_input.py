"""Fail-closed checks for local research inputs."""

import tempfile
import unittest
from pathlib import Path

from recovery.convert_research_bars_for_scene_snapshot import convert
from recovery.export_strategy_research_data import assert_unique_bar_times as check_export
from recovery.run_local_strategy_validation import (
    assert_scene_coverage,
    assert_unique_bar_times as check_validation,
)


class UniqueBarTimesTest(unittest.TestCase):
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
