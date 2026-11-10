"""Freeze one explicit symbol/scene source; prove its four profile signals before PnL."""

import argparse
import json
import re
from pathlib import Path

from recovery import local_strategy_backtest as runner
from recovery.export_representative_candidate import export_candidate
from recovery.run_representative_formal_batch import research_parity_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import execute, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog-dir', 'indsvr-repo', 'sim-repo', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('hypothesis', 'symbol', 'scene'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    for name in ('catalog_dir', 'indsvr_repo', 'sim_repo', 'training_input_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.output_dir.exists():
        raise ValueError('preserve source contract attempt; use a fresh directory')
    parent = json.loads((args.catalog_dir / 'manifest.json').read_text(encoding='utf-8'))
    research = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    if (parent['source_sha256']['StrategyResearchBatchCli'] != sha(research)
            or parent['exporter_sha256'] != sha(Path(__file__).with_name('export_representative_candidate.py'))):
        raise ValueError('frozen catalog/exporter changed')
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    for name, digest in parent['research_class_sha256'].items():
        if sha(class_dir / name) != digest:
            raise ValueError('research bytecode changed')
    row = next(item for item in parent['catalog'] if item['hypothesis'] == args.hypothesis)
    ready = json.loads((args.training_input_dir / 'READY.json').read_text(encoding='utf-8'))
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or args.symbol not in ready['files'] or args.scene not in ('trend', 'range', 'channel', 'breakout', 'reversal')):
        raise ValueError('explicit supported symbol and scene required')
    if not row['family'].startswith('FitOnlyRisk'):
        raise ValueError('only frozen four-profile policies are supported')
    output = args.output_dir
    output.mkdir(parents=True)
    bars = args.training_input_dir / (args.symbol + '-15m.tsv')
    if sha(bars) != ready['files'][args.symbol]['bars_sha256']:
        raise ValueError('training market input changed')
    manifest = {'schema': 'fit_risk_scoped_source_training_contract_v1', 'catalog': [row],
        'source_sha256': parent['source_sha256'], 'parent_catalog_sha256': sha(args.catalog_dir / 'manifest.json'),
        'symbol': args.symbol, 'scene': args.scene, 'training_ready_sha256': sha(args.training_input_dir / 'READY.json'),
        'training_bars_sha256': sha(bars), 'begin': '2023-01-01', 'end': '2023-12-31', 'profiles': [0, 1, 2, 3],
        'exporter_sha256': parent['exporter_sha256'], 'wrapper_sha256': sha(Path(__file__)),
        'financial_validation_started': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    atomic_write_json(output / 'campaign/campaign.json', manifest)
    frozen, name = export_candidate(output / 'campaign', args.indsvr_repo, output / 'frozen',
                                     args.symbol, args.scene, args.hypothesis)
    source = frozen / 'GeneratedStrategy.java'
    folder = output / 'artifacts' / name
    artifact, entry, _ = runner.compile_source(source.read_text(encoding='utf-8'), args.sim_repo, folder)
    cp = research_parity_classpath(args.indsvr_repo, args.sim_repo)
    execute(['java', '-Xmx256m', '-cp', cp,
        'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source',
        str(source), row['family'], name], folder / 'source-validator.log')
    profiles = []
    for profile in range(4):
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', str(bars), args.symbol,
            '2023-01-01', '2023-12-31', args.hypothesis, str(artifact), entry, str(profile)], folder / ('profile-%d.log' % profile))
        counts = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
        if not counts or int(counts[1]) != 35040 or counts[2] != counts[3] or int(counts[4]) != 0:
            raise ValueError('scope training signal parity failed')
        profiles.append({'risk_profile': profile, 'bars': int(counts[1]), 'signals': int(counts[2]),
                         'mismatches': 0, 'nonzero_signal_coverage': int(counts[2]) > 0})
    record = {'hypothesis': args.hypothesis, 'family': row['family'], 'strategy': name,
        'source_sha256': sha(source), 'artifact_sha256': sha(artifact), 'artifact_path': str(artifact),
        'entry_class': entry, 'profiles': profiles, 'manifest_sha256': sha(output / 'manifest.json'),
        'source_validator_passed': True, 'training_only': True, 'financial_validation_started': False, 'production_write': False}
    atomic_write_json(folder / 'contract.json', record)
    atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'completed': 1, 'profile_cases': 4,
        'manifest_sha256': sha(output / 'manifest.json'), 'financial_validation_started': False, 'production_write': False})
    print('FIT_RISK_SCOPE_CONTRACT', name, 'profiles', 4, flush=True)


if __name__ == '__main__':
    main()
