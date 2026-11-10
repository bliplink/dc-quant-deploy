import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from recovery.download_public_training_history import compare_overlap, months, parse_archive


class PublicTrainingHistoryTest(unittest.TestCase):
    def archive(self, name='BTCUSDT-15m-2024-01.csv', row=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zipped:
            zipped.writestr(name, row or '1704067200000,100,101,99,100,123,1704068099999,1,1,1,1,0\n')
        return buf.getvalue()

    def test_pre_validation_month_bounds(self):
        self.assertEqual(['2023-12', '2024-01'], list(months('2023-12', '2024-01')))
        with self.assertRaises(ValueError): list(months('2024-01', '2024-12'))

    def test_parse_official_futures_millisecond_ohlcv(self):
        rows = parse_archive(self.archive(), 'BTCUSDT', '2024-01')
        self.assertEqual('2024-01-01 00:00:00.000000', rows[0][1])

    def test_volume_matches_existing_decimal_storage_not_relaxed_tolerance(self):
        rows = parse_archive(self.archive(row='1704067200000,100,101,99,100,123.456,1704068099999,1,1,1,1,0\n'), 'BTCUSDT', '2024-01')
        self.assertEqual('123.45', rows[0][-1])
        self.assertEqual(('100', '101', '99', '100'), rows[0][2:6])

    def test_reject_zip_traversal_and_wrong_month(self):
        with self.assertRaises(ValueError):
            parse_archive(self.archive('../escape.csv'), 'BTCUSDT', '2024-01')
        with self.assertRaises(ValueError):
            parse_archive(self.archive(row='1703980800000,100,101,99,100,123,1,1,1,1,1,0\n'), 'BTCUSDT', '2024-01')

    def test_overlap_audit_requires_all_price_and_volume_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'original.tsv'; other = root / 'archive.tsv'
            source.write_text('2024-01-01 00:00:00.000000\t100\t101\t99\t100\t123\n', encoding='utf-8')
            other.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
            self.assertTrue(compare_overlap(source, [other], min_rows=1)['passed'])
            other.write_text(source.read_text(encoding='utf-8').replace('\t123', '\t124'), encoding='utf-8')
            self.assertFalse(compare_overlap(source, [other], min_rows=1)['passed'])


if __name__ == '__main__':
    unittest.main()
