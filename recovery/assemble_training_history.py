"""Assemble checksummed older public history without changing financial READY inputs."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from recovery.download_public_training_history import VOLUME_CANONICALIZATION
from recovery.export_strategy_research_data import SYMBOLS
from recovery.strategy_recovery_common import atomic_write_json


CUTOFF = '2024-12-15'
BRIDGE = '2024-08-12'


def append_rows(source, output, previous, first, last):
    count = 0
    with source.open(encoding='utf-8') as stream:
        for row in csv.reader(stream, delimiter='\t'):
            day = row[0][:10]
            if day < first or day >= last:
                continue
            if previous is not None and row[0] <= previous:
                raise ValueError('overlap or out-of-order training rows: ' + str(source))
            output.write('\t'.join(row) + '\n')
            previous = row[0]; count += 1
    return previous, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives-dir', type=Path, required=True)
    parser.add_argument('--overlap-dir', type=Path, required=True)
    parser.add_argument('--existing-input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if (args.output_dir / 'READY.json').exists():
        raise ValueError('training READY already frozen; do not overwrite')
    original_ready = json.loads((args.existing_input_dir / 'READY.json').read_text(encoding='utf-8'))
    archives = json.loads((args.archives_dir / 'DOWNLOAD_COMPLETE.json').read_text(encoding='utf-8'))
    overlap = json.loads((args.overlap_dir / 'DOWNLOAD_COMPLETE.json').read_text(encoding='utf-8'))
    if any(not overlap['overlap'].get(symbol, {}).get('passed') for symbol in SYMBOLS):
        raise ValueError('all 10 source overlap checks must pass')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for symbol in SYMBOLS:
        sources = []
        for root, manifest in ((args.archives_dir, archives), (args.overlap_dir, overlap)):
            for record in manifest['archives']:
                if record['symbol'] != symbol:
                    continue
                if record.get('volume_canonicalization') != VOLUME_CANONICALIZATION:
                    raise ValueError('wrong volume canonicalization')
                path = root / symbol / ('%s-15m-%s.tsv' % (symbol, record['month']))
                if hashlib.sha256(path.read_bytes()).hexdigest() != record['tsv_sha256']:
                    raise ValueError('archive TSV changed')
                sources.append(path)
        prefix = args.existing_input_dir / (symbol + '-15m.tsv')
        if hashlib.sha256(prefix.read_bytes()).hexdigest() != original_ready['files'][symbol]['bars_sha256']:
            raise ValueError('original READY changed')
        destination = args.output_dir / (symbol + '-15m.tsv')
        previous, count = None, 0
        with destination.open('w', encoding='utf-8', newline='\n') as output:
            for source in sorted(sources):
                previous, added = append_rows(source, output, previous, '2022-01-01', BRIDGE)
                count += added
            previous, added = append_rows(prefix, output, previous, BRIDGE, CUTOFF)
            count += added
        files[symbol] = {'bars_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                         'rows': count, 'last_time': previous}
        print('TRAINING_HISTORY', symbol, count, previous, flush=True)
    atomic_write_json(args.output_dir / 'READY.json', {
        'purpose': 'training_only', 'train_end_exclusive': CUTOFF,
        'financial_validation_input_changed': False, 'server_or_llm_calls': 0,
        'original_ready_sha256': hashlib.sha256((args.existing_input_dir / 'READY.json').read_bytes()).hexdigest(),
        'archive_manifest_sha256': hashlib.sha256((args.archives_dir / 'DOWNLOAD_COMPLETE.json').read_bytes()).hexdigest(),
        'overlap_manifest_sha256': hashlib.sha256((args.overlap_dir / 'DOWNLOAD_COMPLETE.json').read_bytes()).hexdigest(),
        'files': files})


if __name__ == '__main__':
    main()
