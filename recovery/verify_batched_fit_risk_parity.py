"""Training-only proof of launch batching; no financial replay, source repair or publication."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

from recovery.run_fit_risk_catalog_batch import verify_full_source_proof
from recovery.run_representative_formal_batch import research_parity_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import FAMILIES, execute, sha


SUMMARY = re.compile(r'^bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+), economics=(.*)$', re.M)


def parity_summary(text):
    found = SUMMARY.findall(text)
    if len(found) != 1:
        raise ValueError('one complete unchanged parity summary required')
    bars, expected, actual, mismatches, economics = found[0]
    if int(bars) != 35040 or expected != actual or int(mismatches) != 0:
        raise ValueError('full training year signal parity failed')
    return {'bars': int(bars), 'signals': int(expected), 'mismatches': 0, 'economics': economics}


def batched_profiles(text):
    if text.count('candidate source validation passed') != 1:
        raise ValueError('original source validator must pass exactly once')
    blocks = re.findall(r'^RISK_PROFILE_BEGIN (\d+)\r?\n(.*?)^RISK_PROFILE_END (\d+)\s*$',
                        text, re.M | re.S)
    markers = re.findall(r'^RISK_PROFILE_(?:BEGIN|END) .*$', text, re.M)
    if len(markers) != 8 or [(begin, end) for begin, _, end in blocks] != [(str(p), str(p)) for p in range(4)]:
        raise ValueError('exact four ordered complete risk-profile blocks required')
    return [dict(parity_summary(body), risk_profile=int(begin)) for begin, body, _ in blocks]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog-dir', 'indsvr-repo', 'sim-repo', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('catalog_dir', 'indsvr_repo', 'sim_repo', 'training_input_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('preserve prior attempt; use a fresh engineering proof directory')
    catalog = read(args.catalog_dir / 'manifest.json')
    source_proof = verify_full_source_proof(args.catalog_dir)
    ready = read(args.training_input_dir / 'READY.json')
    bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(bars) != ready['files']['BTCUSDT']['bars_sha256']
            or sha(args.training_input_dir / 'READY.json') != catalog['training_ready_sha256']):
        raise ValueError('unchanged training-only data required')
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    for name, digest in catalog['research_class_sha256'].items():
        if sha(class_dir / name) != digest:
            raise ValueError('frozen reference bytecode changed: ' + name)
    chosen = []
    for family in FAMILIES:
        row = next(row for row in catalog['catalog'] if row['family'] == 'FitOnlyRisk' + family)
        contract_path = args.catalog_dir / 'artifacts' / row['strategy'] / 'contract.json' if 'strategy' in row else None
        # The catalog declaration is hypothesis-bound, while exact strategy names live in artifacts.
        if contract_path is None:
            matches = [path for path in (args.catalog_dir / 'artifacts').glob('*/contract.json')
                       if read(path)['hypothesis'] == row['hypothesis']]
            if len(matches) != 1:
                raise ValueError('one original source contract per fixed engineering hypothesis required')
            contract_path = matches[0]
        contract = read(contract_path)
        chosen.append({'contract_path': str(contract_path), 'contract_sha256': sha(contract_path),
                       'hypothesis': row['hypothesis'], 'family': row['family'], 'strategy': contract['strategy']})
    java = Path(__file__).with_name('java') / 'FourProfileParityBatchCli.java'
    manifest = {'schema': 'four_profile_launch_batching_training_proof_v1',
        'catalog_manifest_sha256': sha(args.catalog_dir / 'manifest.json'),
        'catalog_completion_sha256': source_proof['completion_sha256'],
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'bars_sha256': sha(bars),
        'java_source_sha256': sha(java), 'wrapper_sha256': sha(Path(__file__)),
        'reference_cli_sha256': sha(class_dir / 'RepresentativeSignalParityCli.class'),
        'cases': chosen, 'financial_validation_started': False, 'new_holdout_read': False,
        'production_write': False}
    output.mkdir(parents=True)
    atomic_write_json(output / 'manifest.json', manifest)
    classes = output / 'classes'
    classes.mkdir()
    reference_cp = research_parity_classpath(args.indsvr_repo, args.sim_repo)
    execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', reference_cp,
             '-d', str(classes), str(java)], output / 'compile.log')
    cp = str(classes) + os.pathsep + reference_cp
    cases = []
    try:
        for case in chosen:
            folder = output / 'cases' / case['strategy']
            contract = read(Path(case['contract_path']))
            source = args.catalog_dir / 'frozen' / case['strategy'] / 'GeneratedStrategy.java'
            artifact = Path(contract['artifact_path'])
            if sha(source) != contract['source_sha256'] or sha(artifact) != contract['artifact_sha256']:
                raise ValueError('frozen source/artifact changed')
            expected = [dict(parity_summary((Path(case['contract_path']).parent / ('profile-%d.log' % p))
                                            .read_text(encoding='utf-8')), risk_profile=p) for p in range(4)]
            started = time.perf_counter()
            stdout = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
                'com.app.dc.service.strategy.research.FourProfileParityBatchCli', str(source),
                case['family'], case['strategy'], str(bars), 'BTCUSDT', '2023-01-01', '2023-12-31',
                case['hypothesis'], str(artifact), contract['entry_class']], folder / 'batched.log')
            actual = batched_profiles(stdout)
            if actual != expected:
                raise ValueError('batching changed original signal/economics results')
            result = dict(case, passed=True, profiles=actual, original_profiles=expected,
                          batched_seconds=time.perf_counter() - started, source_sha256=sha(source),
                          artifact_sha256=sha(artifact), new_holdout_read=False, production_write=False)
            atomic_write_json(folder / 'result.json', result)
            cases.append(result)
            atomic_write_json(output / 'status.json', {'completed': len(cases), 'total': len(chosen),
                'profile_cases': len(cases) * 4, 'financial_validation_started': False, 'production_write': False})
            print('BATCHED_PARITY_PROOF', len(cases), '/', len(chosen), case['hypothesis'], flush=True)
        atomic_write_json(output / 'audit.json', {'state': 'complete', 'cases': len(cases),
            'profile_cases': len(cases) * 4, 'manifest_sha256': sha(output / 'manifest.json'),
            'class_sha256': {str(path.relative_to(classes)): sha(path) for path in classes.rglob('*.class')},
            'result_sha256': {r['strategy']: sha(output / 'cases' / r['strategy'] / 'result.json') for r in cases},
            'financial_validation_started': False, 'new_holdout_read': False, 'production_write': False,
            'completed_utc': datetime.now(timezone.utc).isoformat()})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'error': str(error), 'completed': len(cases),
                                                'production_write': False})
        raise


if __name__ == '__main__':
    main()
