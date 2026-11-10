import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from recovery.verify_fit_validation_replay import training_fixtures


class FitValidationFixtureTest(unittest.TestCase):
    def test_future_perturbation_preserves_all_first_fit_prices_and_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original.tsv'
            point = datetime(2023, 1, 1)
            with original.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write('2022-12-31 23:45:00\t1\t2\t1\t2\t99\n')
                for _ in range(365 * 96):
                    stream.write(point.isoformat(' ') + '\t10\t12\t9\t11\t99.12\n')
                    point += timedelta(minutes=15)
                stream.write('2024-01-01 00:00:00\t1\t2\t1\t2\t99\n')
            bars, changed, scenes = training_fixtures(original, root / 'private-fixture')
            plain_rows = bars.read_bytes().splitlines()
            changed_rows = changed.read_bytes().splitlines()
            self.assertEqual(35040, len(plain_rows))
            self.assertEqual(plain_rows[:120 * 96], changed_rows[:120 * 96])
            for actual, other in zip(plain_rows[120 * 96:], changed_rows[120 * 96:]):
                parts, perturbed = actual.split(b'\t'), other.split(b'\t')
                self.assertEqual(parts[0], perturbed[0])
                self.assertEqual(parts[-1], perturbed[-1])
                self.assertEqual([b'12.0', b'14.4', b'10.8', b'13.2'], perturbed[1:5])
            self.assertEqual({'trend', 'range', 'breakout'}, set(scenes))
            for label, path in scenes.items():
                rows = [line.split('\t') for line in path.read_text(encoding='utf-8').splitlines()]
                self.assertEqual(732, len(rows))
                self.assertEqual({label, 'no_trade'}, {row[1] for row in rows})
                self.assertEqual({'SUCCESS'}, {row[2] for row in rows})

    def test_partial_training_year_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original.tsv'
            original.write_text('2023-01-01 00:00:00\t10\t12\t9\t11\t99\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'complete 2023'):
                training_fixtures(original, root / 'fixture')


if __name__ == '__main__':
    unittest.main()
