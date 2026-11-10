"""Read-only, checksummed Binance USD-M archives for pre-validation training.

Never writes production data or changes the existing validation/holdout READY.
Archives are read in memory, not extracted to filesystem-controlled ZIP paths.
"""

import argparse
import csv
import hashlib
import io
import json
import math
import re
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from recovery.export_strategy_research_data import SYMBOLS
from recovery.strategy_recovery_common import atomic_write_json


BASE = 'https://data.binance.vision/data/futures/um/monthly/klines'
VOLUME_CANONICALIZATION = 'clickhouse_decimal76_scale2_truncate'


def months(first, last):
    begin, end = datetime.strptime(first, '%Y-%m'), datetime.strptime(last, '%Y-%m')
    if first > last or last >= '2024-12':
        raise ValueError('only chronological full months before validation are allowed')
    year, month = begin.year, begin.month
    while (year, month) <= (end.year, end.month):
        yield '%04d-%02d' % (year, month)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def parse_archive(data, symbol, month):
    expected = '%s-15m-%s.csv' % (symbol, month)
    rows = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != [expected]:
            raise ValueError('unexpected archive members')
        with archive.open(expected) as raw:
            for row in csv.reader(io.TextIOWrapper(raw, encoding='utf-8-sig')):
                if row and row[0] == 'open_time':
                    continue
                if len(row) < 12 or not re.fullmatch(r'\d{13}', row[0]):
                    raise ValueError('not canonical futures millisecond OHLCV')
                timestamp = int(row[0])
                stamp = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
                values = [float(value) for value in row[1:6]]
                opened, high, low, close, volume = values
                if stamp.strftime('%Y-%m') != month or timestamp % 900000:
                    raise ValueError('bar outside expected month/grid')
                if (not all(math.isfinite(value) for value in values) or min(values[:4]) <= 0
                        or volume < 0 or high < max(opened, close, low) or low > min(opened, close, high)):
                    raise ValueError('invalid OHLCV values')
                if rows and timestamp <= rows[-1][0]:
                    raise ValueError('duplicate/unordered bars in archive')
                # Match dc.kline/kline_view's existing Decimal(76,2) volume storage.
                # Do not widen comparison tolerance or change OHLC prices.
                volume_text = str(Decimal(row[5]).quantize(Decimal('.01'), rounding=ROUND_DOWN))
                rows.append((timestamp, stamp.strftime('%Y-%m-%d %H:%M:%S.000000'), *row[1:5], volume_text))
    if not rows:
        raise ValueError('empty archive')
    return rows


def fetch(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        return response.read()


def download_one(root, symbol, month):
    stem = '%s-15m-%s' % (symbol, month)
    folder = root / symbol
    folder.mkdir(parents=True, exist_ok=True)
    record_path = folder / (stem + '.json')
    tsv_path = folder / (stem + '.tsv')
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if record.get('volume_canonicalization') != VOLUME_CANONICALIZATION:
            raise ValueError('different canonicalization; use a new output directory')
        if hashlib.sha256(tsv_path.read_bytes()).hexdigest() != record['tsv_sha256']:
            raise ValueError('changed local training checkpoint')
        return record
    url = '%s/%s/15m/%s.zip' % (BASE, symbol, stem)
    checksum = fetch(url + '.CHECKSUM').decode('ascii').strip()
    expected = checksum.split()[0]
    if not re.fullmatch('[0-9a-f]{64}', expected) or checksum.split()[-1] != stem + '.zip':
        raise ValueError('invalid official archive checksum contract')
    data = fetch(url)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('official archive checksum mismatch')
    rows = parse_archive(data, symbol, month)
    tsv = ''.join('\t'.join(row[1:]) + '\n' for row in rows).encode('utf-8')
    tsv_path.write_bytes(tsv)
    record = {'symbol': symbol, 'month': month, 'url': url, 'official_sha256': expected,
        'volume_canonicalization': VOLUME_CANONICALIZATION,
        'archive_bytes': len(data), 'rows': len(rows), 'first_time': rows[0][1],
        'last_time': rows[-1][1], 'tsv_sha256': hashlib.sha256(tsv).hexdigest(),
        'missing_15m_intervals': sum(max(0, (b[0] - a[0]) // 900000 - 1) for a, b in zip(rows, rows[1:])),
        'production_write': False}
    atomic_write_json(record_path, record)
    return record


def compare_overlap(reference, downloaded, min_rows=100):
    originals = {}
    with reference.open(encoding='utf-8') as stream:
        for row in csv.reader(stream, delimiter='\t'):
            originals[row[0]] = [float(v) for v in row[1:6]]
    matches, mismatches = 0, []
    for path in sorted(downloaded):
        with path.open(encoding='utf-8') as stream:
            for row in csv.reader(stream, delimiter='\t'):
                if row[0] not in originals:
                    continue
                matches += 1
                if not all(math.isclose(a, float(b), rel_tol=1e-7, abs_tol=1e-8)
                           for a, b in zip(originals[row[0]], row[1:6])):
                    mismatches.append(row[0])
    return {'overlap_rows': matches, 'mismatched_rows': len(mismatches),
            'first_mismatch_times': mismatches[:8], 'passed': matches >= min_rows and not mismatches,
            'min_rows': min_rows, 'comparison': 'all OHLCV fields rel_tol=1e-7 abs_tol=1e-8'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--first-month', required=True)
    parser.add_argument('--last-month', required=True)
    parser.add_argument('--symbols', default=','.join(SYMBOLS))
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--verify-input-dir', type=Path)
    args = parser.parse_args()
    symbols = args.symbols.split(',')
    if any(symbol not in SYMBOLS for symbol in symbols) or not 1 <= args.workers <= 4:
        parser.error('explicit supported symbols and 1..4 workers required')
    month_list = list(months(args.first_month, args.last_month))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    completed, errors = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(download_one, args.output_dir, symbol, month): (symbol, month)
                 for symbol in symbols for month in month_list}
        for future in as_completed(tasks):
            symbol, month = tasks[future]
            try:
                record = future.result(); completed.append(record)
                print('ARCHIVE', len(completed), '/', len(tasks), symbol, month, record['rows'], flush=True)
            except Exception as error:
                errors.append({'symbol': symbol, 'month': month, 'error': str(error)})
                print('ERROR', symbol, month, str(error), flush=True)
            atomic_write_json(args.output_dir / 'download-status.json', {
                'completed': len(completed), 'total': len(tasks), 'errors': errors,
                'production_write': False})
    if errors:
        raise RuntimeError('incomplete training archives; no completed manifest')
    overlap = {}
    if args.verify_input_dir:
        for symbol in symbols:
            overlap[symbol] = compare_overlap(args.verify_input_dir / (symbol + '-15m.tsv'),
                (args.output_dir / symbol).glob('*.tsv'))
        atomic_write_json(args.output_dir / 'overlap-audit.json', overlap)
        if not all(item['passed'] for item in overlap.values()):
            raise ValueError('official source differs from the existing venue/feed; do not mix training data')
    atomic_write_json(args.output_dir / 'DOWNLOAD_COMPLETE.json', {
        'source': 'Binance official public USD-M futures monthly 15m', 'production_write': False,
        'archives': sorted(completed, key=lambda row: (row['symbol'], row['month'])),
        'overlap': overlap, 'financial_holdout_changed': False})


if __name__ == '__main__':
    main()
