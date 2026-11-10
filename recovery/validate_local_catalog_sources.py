"""Compile every frozen representative and check the real server source contract locally."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from recovery.export_representative_candidate import export_candidate
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.strategy_recovery_common import atomic_write_json


def validate_source_item(args, item, validator):
    folder, name = export_candidate(args.campaign_dir, args.indsvr_repo,
        args.output_dir / 'frozen', 'BTCUSDT', 'trend', item['hypothesis'])
    source_path = folder / 'GeneratedStrategy.java'
    source = source_path.read_text(encoding='utf-8')
    artifact, entry, _ = compile_source(source, args.sim_repo, args.output_dir / 'artifacts' / name)
    result = subprocess.run(['java', '-Xmx384m', '-cp', validator,
        'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source',
        str(source_path), 'Frozen local strategy ' + item['hypothesis'], name],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if result.returncode:
        raise ValueError('server source contract failed: ' + item['hypothesis'] + '\n' + result.stdout + result.stderr)
    # Comparing only source hashes cannot prove javac's output matches current source.
    # Exercise a fixed validation-only month before using the bytecode for PnL selection.
    with (folder / 'pre-screen-signal-parity.log').open('w', encoding='utf-8') as log:
        parity = subprocess.run(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', validator,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
            str(args.input_dir / 'BTCUSDT-15m.tsv'), 'BTCUSDT', '2025-04-14', '2025-05-13',
            item['hypothesis'], str(artifact), entry], stdout=log, stderr=subprocess.STDOUT, timeout=300)
    if parity.returncode:
        raise ValueError('research bytecode/source signal mismatch before financial screening: '
                         + str(folder / 'pre-screen-signal-parity.log'))
    return {'hypothesis': item['hypothesis'], 'source_sha256':
        hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(), 'entry_class': entry,
        'pre_screen_signal_parity': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign-dir', 'indsvr-repo', 'sim-repo', 'output-dir', 'input-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    campaign = json.loads((args.campaign_dir / 'campaign.json').read_text(encoding='utf-8'))
    validator = os.pathsep.join([str(args.indsvr_repo / 'target/test-classes'),
                                str(args.indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    validated = []
    # At most two distinct artifact directories/JVMs; only the main thread writes aggregate ledgers.
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for begin in range(0, len(campaign['catalog']), args.workers):
            batch = campaign['catalog'][begin:begin + args.workers]
            for record in executor.map(lambda item: validate_source_item(args, item, validator), batch):
                validated.append(record)
                atomic_write_json(args.output_dir / 'status.json', {
                    'completed': len(validated), 'total': len(campaign['catalog']),
                    'production_write': False, 'validation': validated})
                print('SOURCE_CONTRACT', len(validated), '/', len(campaign['catalog']), record['hypothesis'], flush=True)
    atomic_write_json(args.output_dir / 'SOURCE_CONTRACT_COMPLETE.json', {
        'completed': len(validated), 'production_write': False,
        'campaign_sha256': hashlib.sha256((args.campaign_dir / 'campaign.json').read_bytes()).hexdigest()})


if __name__ == '__main__':
    main()
