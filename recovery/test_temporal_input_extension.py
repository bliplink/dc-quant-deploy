import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from recovery.assemble_temporal_research_input import append_after
from recovery.export_temporal_holdout_extension import verify_bars, verify_scenes, overlap_rows


class TemporalInputExtensionTest(unittest.TestCase):
    def test_complete_ohlcv_and_scene_times_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root, start = Path(directory), datetime(2025, 10, 13)
            bars = root / 'bars.tsv'
            rows = [(start + timedelta(minutes=15 * i)).isoformat(' ') + '\t100\t101\t99\t100\t12.34\n' for i in range(96)]
            bars.write_text(''.join(rows), encoding='utf-8')
            self.assertEqual(96, verify_bars(bars, start.date(), start.date()))
            bars.write_text(''.join(rows[:-1]), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_bars(bars, start.date(), start.date())
            scenes = root / 'scenes.tsv'
            scene_rows = [(start + timedelta(hours=12 * i)).isoformat(' ') +
                          '\ttrend\tSUCCESS\thistorical_kline_scene\tmarket_scene_v3_historical_kline_v1\n' for i in range(2)]
            scenes.write_text(''.join(scene_rows), encoding='utf-8')
            self.assertEqual(2, verify_scenes(scenes, start.date(), start.date()))
            scenes.write_text(''.join(scene_rows + scene_rows[-1:]), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_scenes(scenes, start.date(), start.date())

    def test_overlap_uses_exact_decimals_without_tolerance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / 'a.tsv', root / 'b.tsv'
            a.write_text('2025-10-12 00:00:00\t100.00\t101\t99\t100\t12.34\n', encoding='utf-8')
            b.write_text('2025-10-12 00:00:00.000000\t100\t101.0\t99\t100\t12.340\n', encoding='utf-8')
            self.assertEqual(overlap_rows(a, '2025-10-12', '2025-10-12', True),
                             overlap_rows(b, '2025-10-12', '2025-10-12', True))
            b.write_text(b.read_text(encoding='utf-8').replace('12.340', '12.341'), encoding='utf-8')
            self.assertNotEqual(overlap_rows(a, '2025-10-12', '2025-10-12', True),
                                overlap_rows(b, '2025-10-12', '2025-10-12', True))

    def test_assembly_preserves_old_bytes_and_only_appends_later_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, extension, target = root / 'old.tsv', root / 'tail.tsv', root / 'new.tsv'
            old = b'2025-10-12\told_value\n'
            source.write_bytes(old)
            extension.write_bytes(b'2025-10-12\tduplicate\n2025-10-13\tnew_value\n')
            append_after(source, extension, target, '2025-10-12')
            self.assertEqual(old, source.read_bytes())
            self.assertEqual(old + b'2025-10-13\tnew_value\n', target.read_bytes())


if __name__ == '__main__':
    unittest.main()
