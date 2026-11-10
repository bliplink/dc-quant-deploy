"""Join a verified read-only tail into a new READY directory; never alter older inputs."""

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from recovery.export_strategy_research_data import SYMBOLS, assert_unique_bar_times
from recovery.export_temporal_holdout_extension import verify_scenes
from recovery.strategy_recovery_common import atomic_write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append_after(source, extension, target, cutoff):
    data = source.read_bytes()
    if not data.endswith(b'\n'):
        raise ValueError('frozen input must terminate at a complete row')
    with target.open('wb') as stream:
        stream.write(data)
        with extension.open('rb') as tail:
            for line in tail:
                if line[:10].decode('ascii') > cutoff:
                    stream.write(line)


def assemble(source, extension, output, protocol_path):
    if output.exists():
        raise ValueError('assembled input must use a new directory')
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    ready = json.loads((source / 'READY.json').read_text(encoding='utf-8'))
    manifest = json.loads((extension / 'manifest.json').read_text(encoding='utf-8'))
    complete = json.loads((extension / 'EXTENSION_COMPLETE.json').read_text(encoding='utf-8'))
    if (protocol.get('protocol_version') != 'temporal_source_research_v2'
            or manifest.get('protocol_sha256') != sha(protocol_path)
            or manifest.get('source_ready_sha256') != sha(source / 'READY.json')
            or complete.get('manifest_sha256') != sha(extension / 'manifest.json')
            or complete.get('production_write') is not False
            or complete.get('read_only_existing_data') is not True
            or ready['end'] != protocol['primary_end_inclusive']
            or str(date.fromisoformat(ready['end']) + timedelta(days=1)) != protocol['holdout_begin']):
        raise ValueError('frozen source/extension/temporal protocol mismatch')
    records = {row['symbol']: row for row in complete['records']}
    if set(records) != set(SYMBOLS) or len(complete['records']) != len(SYMBOLS):
        raise ValueError('extension does not cover the complete cohort')
    for symbol in SYMBOLS:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(source / (symbol + suffix)) != ready['files'][symbol][key] or sha(extension / (symbol + suffix)) != records[symbol][key]:
                raise ValueError('a verified market input changed')
    output.mkdir(parents=True)
    result = {'protocol_version': protocol['protocol_version'], 'clock': 'UTC',
        'begin': ready['begin'], 'end': protocol['holdout_end_inclusive'],
        'primary_end_inclusive': protocol['primary_end_inclusive'],
        'holdout_begin': protocol['holdout_begin'], 'minimum_holdout_calendar_days': 62,
        'symbols': list(SYMBOLS), 'source_ready_sha256': sha(source / 'READY.json'),
        'extension_manifest_sha256': sha(extension / 'manifest.json'),
        'protocol_sha256': sha(protocol_path), 'production_write': False, 'files': {}}
    for symbol in SYMBOLS:
        for suffix in ('-15m.tsv', '-scenes.tsv'):
            append_after(source / (symbol + suffix), extension / (symbol + suffix), output / (symbol + suffix), ready['end'])
        assert_unique_bar_times(output / (symbol + '-15m.tsv'))
        scene_count = verify_scenes(output / (symbol + '-scenes.tsv'),
                                   date.fromisoformat(result['begin']), date.fromisoformat(result['end']))
        # Old frozen byte prefix and the seam were checked, so pre-existing gaps are not silently filled.
        result['files'][symbol] = {'bars_sha256': sha(output / (symbol + '-15m.tsv')),
            'scenes_sha256': sha(output / (symbol + '-scenes.tsv')), 'scene_rows': scene_count,
            'old_prefix_preserved': True, 'extension_overlap_exact': records[symbol]['overlap_exact']}
    atomic_write_json(output / 'READY.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-dir', 'extension-dir', 'output-dir', 'protocol'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.source_dir.resolve(), args.extension_dir.resolve(),
                      args.output_dir.resolve(), args.protocol.resolve())
    print('TEMPORAL_READY', len(result['symbols']), result['begin'], result['end'])


if __name__ == '__main__':
    main()
