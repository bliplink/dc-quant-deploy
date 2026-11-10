"""Freeze/compile all fit-risk sources and compare four profiles on training OHLCV only."""

import argparse
import csv
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from recovery import local_strategy_backtest as runner
from recovery.export_representative_candidate import export_candidate
from recovery.run_representative_formal_batch import research_parity_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import execute, sha


def contract_one(args, row, manifest_hash):
    frozen, name = export_candidate(args.output_dir / 'campaign', args.indsvr_repo,
        args.output_dir / 'frozen', 'BTCUSDT', 'trend', row['hypothesis'])
    folder = args.output_dir / 'artifacts' / name
    checkpoint = folder / 'contract.json'
    source_path = frozen / 'GeneratedStrategy.java'
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if (saved['manifest_sha256'] != manifest_hash or saved['source_sha256'] != sha(source_path)
                or saved['artifact_sha256'] != sha(Path(saved['artifact_path']))):
            raise ValueError('frozen training contract changed')
        return saved
    artifact, entry, _ = runner.compile_source(source_path.read_text(encoding='utf-8'), args.sim_repo, folder)
    cp = research_parity_classpath(args.indsvr_repo, args.sim_repo)
    execute(['java', '-Xmx256m', '-cp', cp,
        'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source',
        str(source_path), row['family'], name], folder / 'source-validator.log')
    profiles = []
    for profile in range(4):
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
            str(args.training_input_dir / 'BTCUSDT-15m.tsv'), 'BTCUSDT', '2023-01-01', '2023-12-31',
            row['hypothesis'], str(artifact), entry, str(profile)], folder / ('profile-%d.log' % profile))
        counts = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
        if not counts or int(counts[1]) != 35040 or counts[2] != counts[3] or int(counts[4]) != 0:
            raise ValueError('four-profile training parity failed: ' + row['hypothesis'])
        profiles.append({'risk_profile': profile, 'bars': int(counts[1]), 'signals': int(counts[2]),
                         'mismatches': 0, 'nonzero_signal_coverage': int(counts[2]) > 0})
    saved = {'hypothesis': row['hypothesis'], 'family': row['family'], 'strategy': name,
        'source_sha256': sha(source_path), 'artifact_sha256': sha(artifact), 'artifact_path': str(artifact),
        'entry_class': entry, 'profiles': profiles, 'manifest_sha256': manifest_hash,
        'source_validator_passed': True, 'training_only': True, 'financial_validation_started': False,
        'production_write': False}
    atomic_write_json(checkpoint, saved)
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'sim-repo', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'sim_repo', 'training_input_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    research = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    text = execute(['java', '-Ddc.research.listRepresentativesOnly=true', '-Ddc.research.cohort=fit_only_risk_v1',
        '-cp', str(args.indsvr_repo / 'target/test-classes'),
        'com.app.dc.service.strategy.research.StrategyRepresentativeCatalogCli'], output / 'catalog.log')
    catalog = list(csv.DictReader(io.StringIO(text), delimiter='\t'))
    if len(catalog) != 400 or len({row['family'] for row in catalog}) != 202:
        raise ValueError('frozen 400-direction, 202-class catalog required')
    manifest = {'schema': 'fit_risk_full_source_training_contract_v1', 'catalog': catalog,
        'source_sha256': {'StrategyResearchBatchCli': sha(research)},
        'research_class_sha256': {path.name: sha(path) for path in sorted(class_dir.glob('*.class'))},
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'),
        'training_btc_sha256': sha(args.training_input_dir / 'BTCUSDT-15m.tsv'),
        'begin': '2023-01-01', 'end': '2023-12-31', 'profiles': [0, 1, 2, 3],
        'exporter_sha256': sha(Path(__file__).with_name('export_representative_candidate.py')),
        'wrapper_sha256': sha(Path(__file__)), 'financial_validation_started': False,
        'production_write': False, 'new_holdout_read': False}
    manifest_path = output / 'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
        raise ValueError('catalog engineering attempt changed; use a new directory')
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(output / 'campaign/campaign.json', manifest)
    records = []
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for begin in range(0, len(catalog), args.workers):
                batch = catalog[begin:begin + args.workers]
                for result in pool.map(lambda row: contract_one(args, row, sha(manifest_path)), batch):
                    records.append(result)
                    atomic_write_json(output / 'status.json', {'completed': len(records), 'total': len(catalog),
                        'financial_validation_started': False, 'production_write': False, 'records': records})
                    print('FIT_RISK_SOURCE_CONTRACT', len(records), '/', len(catalog), result['hypothesis'], flush=True)
        atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'completed': len(records),
            'profile_cases': len(records) * 4, 'manifest_sha256': sha(manifest_path),
            'zero_signal_profile_cases': sum(not row['nonzero_signal_coverage'] for r in records for row in r['profiles']),
            'training_only': True, 'financial_validation_started': False, 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error),
            'financial_validation_started': False, 'production_write': False})
        raise


if __name__ == '__main__':
    main()
