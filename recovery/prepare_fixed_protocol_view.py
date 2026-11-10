"""Copy unchanged temporal OHLCV/scene bytes to a new frozen protocol-specific input view."""

import argparse
import json
import shutil
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-dir', 'protocol', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    parent = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    protocol = json.loads(args.protocol.read_text(encoding='utf-8'))
    if args.output_dir.exists():
        raise ValueError('protocol view must be new; preserve all existing financial inputs')
    if (protocol['protocol_version'] != 'temporal_source_research_v2'
            or protocol['selection_mode'] != 'fixed_source_no_parameter_grid'
            or parent['begin'] != protocol['primary_begin']
            or parent['primary_end_inclusive'] != protocol['primary_end_inclusive']
            or parent['holdout_begin'] != protocol['holdout_begin']
            or parent['end'] != protocol['holdout_end_inclusive']):
        raise ValueError('temporal boundaries must remain completely unchanged')
    args.output_dir.mkdir(parents=True)
    for symbol in parent['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            source = args.input_dir / (symbol + suffix)
            if sha(source) != parent['files'][symbol][key]:
                raise ValueError('parent market input changed')
            target = args.output_dir / source.name
            shutil.copyfile(source, target)
            if sha(target) != parent['files'][symbol][key]:
                raise ValueError('copied market input changed')
    ready = dict(parent, protocol_sha256=sha(args.protocol), source_cohort=protocol['source_cohort'],
        source_ready_sha256=sha(args.input_dir / 'READY.json'), raw_market_and_scene_bytes_unchanged=True,
        protocol_view_only=True, production_write=False)
    atomic_write_json(args.output_dir / 'READY.json', ready)
    print('FIXED_PROTOCOL_INPUT_VIEW_READY symbols', len(parent['symbols']), 'market_bytes_unchanged', True)


if __name__ == '__main__':
    main()
