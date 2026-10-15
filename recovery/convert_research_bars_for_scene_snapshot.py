"""Convert canonical research 15m TSV to the local scene snapshot tool's JSONL input."""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from recovery.export_strategy_research_data import assert_unique_bar_times


def convert(source, target):
    assert_unique_bar_times(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with source.open('r', encoding='utf-8', newline='') as rows, \
            target.open('w', encoding='utf-8', newline='') as output:
        for row in csv.reader(rows, delimiter='\t'):
            if len(row) != 6:
                raise ValueError('research bar must have six TSV fields')
            # ClickHouse timezone() on 126 is UTC. Run the Java snapshot tool with
            # -Duser.timezone=UTC so its as-of cutoff uses the same clock.
            start = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
            start_ms = int(start.timestamp() * 1000)
            result = {'starttimems': start_ms, 'endtimems': start_ms + 15 * 60 * 1000,
                      'open': float(row[1]), 'high': float(row[2]),
                      'low': float(row[3]), 'close': float(row[4]),
                      'volume': float(row[5])}
            output.write(json.dumps(result, separators=(',', ':')) + '\n')
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--symbol', required=True)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    if not symbol.isalnum():
        parser.error('--symbol must be alphanumeric')
    source = args.input_dir / (symbol + '-15m.tsv')
    target = args.output_dir / (symbol + '_15M.jsonl')
    print('%s: %d bars' % (target, convert(source, target)))


if __name__ == '__main__':
    main()
