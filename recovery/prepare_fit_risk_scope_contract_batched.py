"""Freeze the same scoped source with proven launch batching, never financial selection."""

import argparse
import json
import os
from pathlib import Path

from recovery import local_strategy_backtest as runner
from recovery.export_representative_candidate import export_candidate
from recovery.run_representative_formal_batch import research_parity_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_batched_fit_risk_parity import batched_profiles
from recovery.verify_fit_only_risk_contract import execute, sha


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_batching_proof(proof, catalog_dir, training_input, indsvr_repo):
    audit, manifest = read(proof / 'audit.json'), read(proof / 'manifest.json')
    java = Path(__file__).with_name('java') / 'FourProfileParityBatchCli.java'
    original_cli = indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    if ((proof / 'FAILED.json').exists() or audit.get('state') != 'complete'
            or audit.get('cases') != 8 or audit.get('profile_cases') != 32
            or audit.get('manifest_sha256') != sha(proof / 'manifest.json')
            or audit.get('financial_validation_started') is not False or audit.get('new_holdout_read') is not False
            or audit.get('production_write') is not False
            or manifest.get('catalog_manifest_sha256') != sha(catalog_dir / 'manifest.json')
            or manifest.get('training_ready_sha256') != sha(training_input / 'READY.json')
            or manifest.get('java_source_sha256') != sha(java)
            or manifest.get('wrapper_sha256') != sha(Path(__file__).with_name('verify_batched_fit_risk_parity.py'))
            or manifest.get('reference_cli_sha256') != sha(original_cli)):
        raise ValueError('complete unchanged eight-case/32-profile training batching proof required')
    classes = proof / 'classes'
    actual_classes = {str(path.relative_to(classes)): sha(path) for path in classes.rglob('*.class')}
    if not actual_classes or actual_classes != audit.get('class_sha256'):
        raise ValueError('batching driver bytecode changed')
    cases = manifest.get('cases', [])
    if len(cases) != 8 or len({row['strategy'] for row in cases}) != 8:
        raise ValueError('eight distinct original engineering cases required')
    if set(audit.get('result_sha256', {})) != {row['strategy'] for row in cases}:
        raise ValueError('missing batching proof case hashes')
    for case in cases:
        result_path = proof / 'cases' / case['strategy'] / 'result.json'
        result = read(result_path)
        if (sha(result_path) != audit['result_sha256'][case['strategy']] or result.get('passed') is not True
                or result.get('new_holdout_read') is not False or result.get('production_write') is not False
                or result.get('profiles') != result.get('original_profiles')
                or [r['risk_profile'] for r in result.get('profiles', [])] != [0, 1, 2, 3]
                or any(r['bars'] != 35040 or r['mismatches'] != 0 for r in result['profiles'])
                or sha(Path(case['contract_path'])) != case['contract_sha256']):
            raise ValueError('original training case or batching result changed')
    return sha(proof / 'manifest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog-dir', 'indsvr-repo', 'sim-repo', 'training-input-dir', 'output-dir', 'batching-proof-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('hypothesis', 'symbol', 'scene'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    for name in ('catalog_dir', 'indsvr_repo', 'sim_repo', 'training_input_dir', 'output_dir', 'batching_proof_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.output_dir.exists():
        raise ValueError('preserve prior source contract attempt; use a fresh directory')
    parent = read(args.catalog_dir / 'manifest.json')
    research = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    if (parent['source_sha256']['StrategyResearchBatchCli'] != sha(research)
            or parent['exporter_sha256'] != sha(Path(__file__).with_name('export_representative_candidate.py'))):
        raise ValueError('frozen source/exporter changed')
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    for name, digest in parent['research_class_sha256'].items():
        if sha(class_dir / name) != digest:
            raise ValueError('research bytecode changed')
    proof_hash = require_batching_proof(args.batching_proof_dir, args.catalog_dir,
                                       args.training_input_dir, args.indsvr_repo)
    row = next(item for item in parent['catalog'] if item['hypothesis'] == args.hypothesis)
    ready = read(args.training_input_dir / 'READY.json')
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or args.symbol not in ready['files'] or args.scene not in ('trend', 'range', 'channel', 'breakout', 'reversal')
            or not row['family'].startswith('FitOnlyRisk')):
        raise ValueError('explicit supported four-profile source scope required')
    bars = args.training_input_dir / (args.symbol + '-15m.tsv')
    if sha(bars) != ready['files'][args.symbol]['bars_sha256']:
        raise ValueError('training market input changed')
    output = args.output_dir
    output.mkdir(parents=True)
    manifest = {'schema': 'fit_risk_scoped_source_training_contract_batched_v1', 'catalog': [row],
        'source_sha256': parent['source_sha256'], 'parent_catalog_sha256': sha(args.catalog_dir / 'manifest.json'),
        'symbol': args.symbol, 'scene': args.scene, 'training_ready_sha256': sha(args.training_input_dir / 'READY.json'),
        'training_bars_sha256': sha(bars), 'begin': '2023-01-01', 'end': '2023-12-31', 'profiles': [0, 1, 2, 3],
        'exporter_sha256': parent['exporter_sha256'], 'wrapper_sha256': sha(Path(__file__)),
        'batching_proof_manifest_sha256': proof_hash, 'financial_validation_started': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    atomic_write_json(output / 'campaign/campaign.json', manifest)
    frozen, name = export_candidate(output / 'campaign', args.indsvr_repo, output / 'frozen',
                                     args.symbol, args.scene, args.hypothesis)
    source = frozen / 'GeneratedStrategy.java'
    folder = output / 'artifacts' / name
    artifact, entry, _ = runner.compile_source(source.read_text(encoding='utf-8'), args.sim_repo, folder)
    cp = str(args.batching_proof_dir / 'classes') + os.pathsep + research_parity_classpath(args.indsvr_repo, args.sim_repo)
    text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
        'com.app.dc.service.strategy.research.FourProfileParityBatchCli', str(source), row['family'], name,
        str(bars), args.symbol, '2023-01-01', '2023-12-31', args.hypothesis, str(artifact), entry],
        folder / 'four-profiles.log')
    profiles = [dict(risk_profile=p['risk_profile'], bars=p['bars'], signals=p['signals'],
                     mismatches=0, nonzero_signal_coverage=p['signals'] > 0) for p in batched_profiles(text)]
    record = {'hypothesis': args.hypothesis, 'family': row['family'], 'strategy': name,
        'source_sha256': sha(source), 'artifact_sha256': sha(artifact), 'artifact_path': str(artifact),
        'entry_class': entry, 'profiles': profiles, 'manifest_sha256': sha(output / 'manifest.json'),
        'source_validator_passed': True, 'training_only': True, 'financial_validation_started': False, 'production_write': False}
    atomic_write_json(folder / 'contract.json', record)
    atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'completed': 1, 'profile_cases': 4,
        'manifest_sha256': sha(output / 'manifest.json'), 'financial_validation_started': False, 'production_write': False})
    print('BATCHED_FIT_RISK_SCOPE_CONTRACT', name, 'profiles', 4, flush=True)


if __name__ == '__main__':
    main()
