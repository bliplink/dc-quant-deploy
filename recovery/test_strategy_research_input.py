"""Fail-closed checks for local research inputs."""

import tempfile
import unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
