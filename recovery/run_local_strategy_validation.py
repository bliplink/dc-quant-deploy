"""Run a pinned, validation-only local research cohort without exposing forward PnL."""

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SYMBOLS = ('ADAUSDT', 'BNBUSDT', 'BTCUSDT', 'DOGEUSDT', 'ETHUSDT',
           'LINKUSDT', 'SOLUSDT', 'TRXUSDT', 'UNIUSDT', 'XRPUSDT')


def assert_unique_bar_times(path):
    previous = None
    with path.open('rb') as stream:
        for line_number, line in enumerate(stream, 1):
            timestamp = line.split(b'\t', 1)[0]
            if not timestamp or (previous is not None and timestamp <= previous):
                raise ValueError(
                    '%s has a duplicate or unordered startTime at line %d' %
                    (path.name, line_number)
                )
            previous = timestamp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--java', required=True)
    parser.add_argument('--classes', required=True)
    parser.add_argument('--input-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--scene', choices=('trend', 'range', 'channel', 'breakout', 'reversal'), required=True)
    parser.add_argument('--cohort', required=True)
    parser.add_argument('--pattern', required=True)
    parser.add_argument('--begin', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--symbols', default=','.join(SYMBOLS))
    parser.add_argument('--java-heap-mb', type=int, default=256)
    args = parser.parse_args()
    if not 64 <= args.java_heap_mb <= 1024:
        parser.error('--java-heap-mb must be between 64 and 1024')
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    symbols = [item.strip().upper() for item in args.symbols.split(',') if item.strip()]
    all_rows = []
    fieldnames = None
    for symbol in symbols:
        assert_unique_bar_times(Path(args.input_dir) / (symbol + '-15m.tsv'))
        command = [args.java, '-Xms16m', '-Xmx%dm' % args.java_heap_mb,
                   '-XX:+UseSerialGC',
                   '-Ddc.research.inputDir=' + args.input_dir,
                   '-Ddc.research.symbols=' + symbol,
                   '-Ddc.research.scene=' + args.scene,
                   '-Ddc.research.cohort=' + args.cohort,
                   '-Ddc.research.hypothesisPattern=' + args.pattern,
                   '-Ddc.research.walkForwardBegin=' + args.begin,
                   '-Ddc.research.walkForwardEnd=' + args.end,
                   '-Ddc.research.validationOnly=true', '-Ddc.research.years=2026',
                   '-cp', args.classes,
                   'com.app.dc.service.strategy.research.StrategyResearchBatchCli']
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        if completed.returncode:
            raise RuntimeError(
                f'{symbol} validation failed (exit {completed.returncode}): '
                f'{completed.stderr.strip() or completed.stdout.strip()}'
            )
        reader = csv.DictReader(completed.stdout.splitlines(), delimiter='\t')
        fieldnames = reader.fieldnames
        rows = list(reader)
        if any(row['wf_forward_bps'] != 'WITHHELD' for row in rows):
            raise RuntimeError('Forward metrics were exposed; refusing research output')
        all_rows.extend(rows)
        print(symbol, 'tested', len(rows), 'validation_pass',
              sum(row['accepted'] == 'YES' for row in rows), flush=True)
    with (output / 'validation_results.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter='\t')
        writer.writeheader()
        writer.writerows(all_rows)
    passing = [row for row in all_rows if row['accepted'] == 'YES']
    with (output / 'validation_pass.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter='\t')
        writer.writeheader()
        writer.writerows(passing)
    metadata = {'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'scene': args.scene, 'cohort': args.cohort, 'pattern': args.pattern,
                'begin': args.begin, 'end': args.end, 'symbols': symbols,
                'tested': len(all_rows), 'validation_pass': len(passing),
                'input_sha256': {name: hashlib.sha256((Path(args.input_dir) / name).read_bytes()).hexdigest()
                                 for symbol in symbols
                                 for name in (symbol + '-15m.tsv', symbol + '-scenes.tsv')},
                'bar_time_contract': 'one canonical kline_view row per startTime; scene cursor uses startTime'}
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps({'tested': len(all_rows), 'validation_pass': len(passing)}, indent=2))


if __name__ == '__main__':
    main()
