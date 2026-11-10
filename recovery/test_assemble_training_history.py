import io
import tempfile
import unittest
from pathlib import Path

from recovery.assemble_training_history import append_rows


class AssembleTrainingHistoryTest(unittest.TestCase):
    def test_cutoff_and_bridge_are_half_open_and_original_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.tsv'
            text = ''.join(day + ' 00:00:00.000000\t1\t2\t1\t2\t3\n'
                           for day in ('2024-08-11', '2024-08-12', '2024-12-14', '2024-12-15'))
            source.write_text(text, encoding='utf-8')
            output = io.StringIO()
            last, count = append_rows(source, output, None, '2024-08-12', '2024-12-15')
            self.assertEqual(2, count)
            self.assertEqual('2024-12-14 00:00:00.000000', last)
            self.assertNotIn('2024-08-11', output.getvalue())
            self.assertNotIn('2024-12-15', output.getvalue())
            self.assertEqual(text, source.read_text(encoding='utf-8'))

    def test_cannot_merge_duplicate_or_unordered_training_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.tsv'
            source.write_text('2024-08-12 00:00:00.000000\t1\t2\t1\t2\t3\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'overlap'):
                append_rows(source, io.StringIO(), '2024-08-12 00:00:00.000000', '2024-01-01', '2024-12-15')


if __name__ == '__main__':
    unittest.main()
