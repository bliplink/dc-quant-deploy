"""Assemble a complete, locally generated historical-scene research input.

This reads only local files. It refuses incomplete campaigns and publishes the
assembled directory only after every source and 12-hour timestamp is verified.
"""

import argparse
import csv
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

from recovery.export_strategy_research_data import SYMBOLS, assert_unique_bar_times
from recovery.run_local_historical_scene_campaign import (
    date_chunks, expected_times, sha256, validate_rows, write_json,
)


def read_existing_scenes(path, begin, end):
    expected = expected_times(begin, end)
    result = {}
    with path.open('r', encoding='utf-8', newline='') as source:
        for row in csv.reader(source, delimiter='\t'):
            if len(row) != 5 or row[2:] != [
                    'SUCCESS', 'historical_kline_scene',
                    'market_scene_v3_historical_kline_v1']:
                raise ValueError('unexpected canonical scene row in %s' % path)
            stamp = row[0]
            if stamp in result:
                raise ValueError('duplicate canonical scene time %s' % stamp)
            result[stamp] = row
    if set(result) != expected:
        raise ValueError('canonical scenes incomplete in %s: missing=%d unexpected=%d' %
                         (path, len(expected - set(result)), len(set(result) - expected)))
    return result


def verified_generated_scenes(campaign_dir, symbol, begin, end, chunk_days, model,
                              usable_begin=None):
    result = {}
    sources = []
    for first, last in date_chunks(begin, end, chunk_days):
        chunk = campaign_dir / 'chunks' / symbol / (
            first.isoformat() + '_' + last.isoformat())
        checkpoint_path = chunk / 'checkpoint.json'
        if not checkpoint_path.is_file():
            raise ValueError('campaign chunk has no checkpoint: %s' % chunk)
        checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        rows_path = Path(checkpoint['rows_file']).resolve()
        if not rows_path.is_relative_to(chunk.resolve()):
            raise ValueError('checkpoint rows file is outside its chunk: %s' % chunk)
        if (checkpoint['symbol'], checkpoint['begin'], checkpoint['end']) != (
                symbol, first.isoformat(), last.isoformat()):
            raise ValueError('checkpoint identity mismatch: %s' % chunk)
        stats = validate_rows(rows_path, symbol, first, last, model)
        if stats['sha256'] != checkpoint['rows_sha256'] or stats['rows'] != checkpoint['rows']:
            raise ValueError('checkpoint content mismatch: %s' % chunk)
        with rows_path.open('r', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                stamp = row['run_time']
                if stamp in result:
                    raise ValueError('duplicate generated scene time %s' % stamp)
                result[stamp] = row
        sources.append({'chunk': str(chunk), 'rows_sha256': stats['sha256']})
    if set(result) != expected_times(begin, end):
        raise ValueError('generated scene range incomplete for ' + symbol)
    if usable_begin is not None:
        cutoff = usable_begin.isoformat() + ' 00:00:00'
        result = {stamp: row for stamp, row in result.items() if stamp >= cutoff}
        for stamp, row in result.items():
            quality = json.loads(row.get('data_quality_json') or '{}')
            if any(quality.get(interval, {}).get('quality') != 'GOOD'
                   for interval in ('1d', '1h', '15m')):
                raise ValueError('low-quality generated scene after usable_begin: %s %s' %
                                 (symbol, stamp))
    return {stamp: [stamp, row['scene'], row['status'], row['analysis_type'],
                    row['prompt_version']] for stamp, row in result.items()}, sources


def assemble(input_dir, campaign_dir, output_dir, existing_end):
    campaign = json.loads((campaign_dir / 'campaign.json').read_text(encoding='utf-8'))
    begin = date.fromisoformat(campaign['begin'])
    end = date.fromisoformat(campaign['end'])
    if (campaign['symbols'] != list(SYMBOLS) or campaign['clock'] != 'UTC'
            or campaign['output_mode'] != 'export_rows_only_no_production_write'
            or existing_end < end + timedelta(days=1)):
        raise ValueError('unexpected campaign contract or canonical scene range')
    existing_begin = end + timedelta(days=1)
    usable_begin = date(2024, 12, 15)
    if not begin < usable_begin <= end:
        raise ValueError('research quality cutoff is outside the campaign')
    model = campaign['model']
    stage = output_dir.with_name(output_dir.name + '.assembling')
    if output_dir.exists() or stage.exists():
        raise FileExistsError('assembled output or staging directory already exists')

    # Verify the entire cohort before creating any output. In particular, a
    # partial campaign must never be mistaken for an extended research sample.
    verified = {}
    for symbol in SYMBOLS:
        bars = input_dir / (symbol + '-15m.tsv')
        if sha256(bars) != campaign['input_sha256'][symbol]:
            raise ValueError('research bars changed for ' + symbol)
        assert_unique_bar_times(bars)
        generated, sources = verified_generated_scenes(
            campaign_dir, symbol, begin, end, campaign['chunk_days'], model,
            usable_begin)
        canonical = read_existing_scenes(
            input_dir / (symbol + '-scenes.tsv'), existing_begin, existing_end)
        overlap = set(generated) & set(canonical)
        if overlap:
            raise ValueError('generated and canonical scenes overlap for ' + symbol)
        verified[symbol] = (bars, generated, canonical, sources)

    stage.mkdir(parents=True)
    metadata = {'begin': usable_begin.isoformat(), 'end': existing_end.isoformat(),
                'model': model, 'symbols': list(SYMBOLS), 'clock': 'UTC',
                'source_campaign': str(campaign_dir.resolve()),
                'pre_usable_labels': 'verified_but_excluded', 'files': {}}
    for symbol, (bars, generated, canonical, sources) in verified.items():
        output_bars = stage / bars.name
        output_scenes = stage / (symbol + '-scenes.tsv')
        shutil.copyfile(bars, output_bars)
        with output_scenes.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            for stamp in sorted(generated):
                writer.writerow(generated[stamp])
            for stamp in sorted(canonical):
                writer.writerow(canonical[stamp])
        metadata['files'][symbol] = {
            'bars_sha256': sha256(output_bars),
            'scenes_sha256': sha256(output_scenes),
            'generated_rows': len(generated), 'canonical_rows': len(canonical),
            'generated_sources': sources,
        }
    write_json(stage / 'READY.json', metadata)
    stage.rename(output_dir)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--campaign-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--existing-end', type=date.fromisoformat,
                        default=date(2025, 10, 12))
    args = parser.parse_args()
    metadata = assemble(args.input_dir.resolve(), args.campaign_dir.resolve(),
                        args.output_dir.resolve(), args.existing_end)
    print('assembled', len(metadata['symbols']), 'symbols into', args.output_dir)


if __name__ == '__main__':
    main()
