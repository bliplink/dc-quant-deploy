"""Run a pinned, validation-only local research cohort without exposing forward PnL."""

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
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


def assert_scene_coverage(path, begin, end):
    first = None
    last = None
    with path.open('r', encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            stamp = datetime.fromisoformat(line.split('\t', 1)[0])
            if last is not None and stamp < last:
                raise ValueError('%s has unordered scene times' % path.name)
            if first is None:
                first = stamp
            last = stamp
    if first is None or first > datetime.fromisoformat(begin) or last < datetime.fromisoformat(end):
        raise ValueError(
            '%s does not cover the requested research window %s~%s' %
            (path.name, begin, end)
        )


def assert_research_protocol(protocol_path, input_dir, begin, end, symbols):
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    ready_path = input_dir / 'READY.json'
    ready = json.loads(ready_path.read_text(encoding='utf-8'))
    if (protocol.get('protocol_version') != 'older_direct_scene_research_v1'
            or protocol.get('selection_mode') != 'validation_only_forward_withheld'
            or protocol.get('production_write') is not False):
        raise ValueError('unsupported research protocol')
    if (begin != protocol['screen_begin'] or end != protocol['screen_end_inclusive']
            or date.fromisoformat(protocol['holdout_begin']) !=
            date.fromisoformat(end) + timedelta(days=1)):
        raise ValueError('research dates would expose the holdout window')
    if (ready.get('begin') != protocol['required_ready_begin']
            or ready.get('end') != protocol['required_ready_end']
            or ready.get('model') != protocol['required_scene_model']
            or ready.get('clock') != 'UTC'):
        raise ValueError('research input READY contract mismatch')
    if (date.fromisoformat(protocol['holdout_end_inclusive']) >
            date.fromisoformat(ready['end'])):
        raise ValueError('holdout extends beyond READY input')
    for symbol in symbols:
        files = ready.get('files', {}).get(symbol)
        if files is None:
            raise ValueError('READY has no symbol ' + symbol)
        for suffix, field in (('-15m.tsv', 'bars_sha256'),
                              ('-scenes.tsv', 'scenes_sha256')):
            path = input_dir / (symbol + suffix)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != files.get(field):
                raise ValueError('READY file hash mismatch: ' + path.name)
    return hashlib.sha256(protocol_path.read_bytes()).hexdigest()


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
    parser.add_argument('--protocol', type=Path,
                        help='Freeze the older-data validation window and READY input hashes')
    args = parser.parse_args()
    if not 64 <= args.java_heap_mb <= 1024:
        parser.error('--java-heap-mb must be between 64 and 1024')
    symbols = [item.strip().upper() for item in args.symbols.split(',') if item.strip()]
    protocol_sha256 = (assert_research_protocol(
        args.protocol, Path(args.input_dir), args.begin, args.end, symbols)
        if args.protocol else None)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    all_rows = []
    fieldnames = None
    for symbol in symbols:
        assert_unique_bar_times(Path(args.input_dir) / (symbol + '-15m.tsv'))
        assert_scene_coverage(Path(args.input_dir) / (symbol + '-scenes.tsv'),
                              args.begin, args.end)
        command = [args.java, '-Xms16m', '-Xmx%dm' % args.java_heap_mb,
                   '-XX:+UseSerialGC',
                   '-Ddc.research.inputDir=' + args.input_dir,
                   '-Ddc.research.symbols=' + symbol,
                   '-Ddc.research.scene=' + args.scene,
                   '-Ddc.research.cohort=' + args.cohort,
                   '-Ddc.research.hypothesisPattern=' + args.pattern,
                   '-Ddc.research.walkForwardBegin=' + args.begin,
                   '-Ddc.research.walkForwardEnd=' + args.end,
                   '-Ddc.research.validationOnly=true',
                   '-Ddc.research.years=' + str(date.fromisoformat(args.end).year),
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
    if protocol_sha256:
        metadata['protocol_sha256'] = protocol_sha256
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps({'tested': len(all_rows), 'validation_pass': len(passing)}, indent=2))


if __name__ == '__main__':
    main()
