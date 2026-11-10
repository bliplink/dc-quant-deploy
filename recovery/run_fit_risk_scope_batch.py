"""Frozen balanced OHLCV research queue; qualified sources still require review and server validation."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from recovery.run_fit_risk_admission import require_proof
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import FAMILIES, sha


SCENES = ('trend', 'range', 'channel', 'breakout', 'reversal')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def strategy_name(symbol, scene, hypothesis):
    digest = hashlib.sha256((symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:12]
    return 'catalog_' + symbol.lower() + '_' + scene + '_' + digest


def build_queue(source_contract_dir, input_dir):
    proof = read(source_contract_dir / 'audit.json')
    if (proof.get('state') != 'complete' or proof.get('source_contracts') != 8
            or proof.get('profile_signal_parity_cases') != 32
            or proof.get('manifest_sha256') != sha(source_contract_dir / 'manifest.json')):
        raise ValueError('pre-financial eight-family structural engineering cohort required')
    seeds = [read(path)['strategies'][0] for path in (source_contract_dir / 'frozen').glob('*/seed.json')]
    hypotheses = []
    for family in FAMILIES:
        item = next(item for item in seeds if item['request']['logicSummary'].split(';')[0] == 'FitOnlyRisk' + family)
        hypotheses.append((item['request']['sourceRef'].split(':')[-1], 'FitOnlyRisk' + family))
    if len({name for name, _ in hypotheses}) != 8:
        raise ValueError('structural hypotheses must be distinct')
    symbols = sorted(read(input_dir / 'READY.json')['symbols'])
    if len(symbols) != 10:
        raise ValueError('fixed ten-symbol research corpus required')
    return [dict(symbol=symbol, scene=scene, hypothesis=hypothesis, family=family,
                 strategy=strategy_name(symbol, scene, hypothesis))
            for symbol in symbols for scene in SCENES for hypothesis, family in hypotheses]


def completed_observation(admission, item, expected, proof_hash):
    saved = read(admission / 'manifest.json')
    completed = read(admission / 'FORMAL_COMPLETE.json')
    if (completed['manifest_sha256'] != sha(admission / 'manifest.json')
            or saved['protocol_sha256'] != expected['protocol_sha256']
            or saved['ready_sha256'] != expected['ready_sha256']
            or saved['fit_validation_oracle_manifest_sha256'] != proof_hash):
        raise ValueError('completed financial observation provenance changed')
    records = read(admission / 'results.json')
    if 'results_sha256' in completed and completed['results_sha256'] != sha(admission / 'results.json'):
        raise ValueError('completed financial results changed')
    for name, digest in completed.get('financial_outputs_sha256', {}).items():
        if sha(admission / name) != digest:
            raise ValueError('completed financial metrics changed')
    if len(records) != 1:
        raise ValueError('one fixed-source result required')
    record = records[0]
    source = admission / 'frozen' / item['strategy'] / 'GeneratedStrategy.java'
    if (record['source_sha256'] != saved['source_sha256'] or sha(source) != record['source_sha256']
            or any(record[key] != item[key] for key in ('strategy', 'symbol', 'scene', 'hypothesis', 'family'))):
        raise ValueError('financial result source/scope changed')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog-dir', 'source-contract-dir', 'indsvr-repo', 'sim-repo', 'training-input-dir',
                 'input-dir', 'protocol', 'oracle-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--reuse-admission', type=Path, action='append', default=[])
    parser.add_argument('--reuse-contract', type=Path, action='append', default=[])
    args = parser.parse_args()
    for name in ('catalog_dir', 'source_contract_dir', 'indsvr_repo', 'sim_repo', 'training_input_dir',
                 'input_dir', 'protocol', 'oracle_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    proof_hash = require_proof(args.oracle_dir, Path(__file__).with_name('java'), args.sim_repo)
    queue = build_queue(args.source_contract_dir, args.input_dir)
    reuse_admissions = {}
    for directory in args.reuse_admission:
        directory = directory.resolve()
        result = read(directory / 'results.json')[0]
        if not (directory / 'FORMAL_COMPLETE.json').exists() or result['strategy'] in reuse_admissions:
            raise ValueError('reuse only one complete original financial result per strategy')
        reuse_admissions[result['strategy']] = directory
    reuse_contract_roots = [directory.resolve() for directory in args.reuse_contract]
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    tool_names = ('run_fit_risk_scope_batch.py', 'prepare_fit_risk_scope_contract.py', 'run_fit_risk_admission.py',
                  'export_representative_candidate.py')
    manifest = {'schema': 'frozen_balanced_fit_risk_scope_queue_v1', 'queue': queue,
        'catalog_sha256': sha(args.catalog_dir / 'manifest.json'),
        'structural_selection_proof_sha256': sha(args.source_contract_dir / 'manifest.json'),
        'structural_seed_sha256': {path.parent.name: sha(path)
            for path in (args.source_contract_dir / 'frozen').glob('*/seed.json')},
        'oracle_manifest_sha256': proof_hash, 'ready_sha256': sha(args.input_dir / 'READY.json'),
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'protocol_sha256': sha(args.protocol),
        'tools_sha256': {name: sha(Path(__file__).with_name(name)) for name in tool_names},
        'reuse_admissions': {key: str(value) for key, value in reuse_admissions.items()},
        'reuse_admission_sha256': {name: {path.name: sha(path) for path in directory.glob('*.json')}
                                   for name, directory in reuse_admissions.items()},
        'reuse_contract_roots': list(map(str, reuse_contract_roots)),
        'hypothesis_selection': 'eight_structural_families_frozen_in_pre_financial_engineering_contract',
        'server_codegen_allowed': False, 'production_write': False}
    manifest_path = output / 'manifest.json'
    if manifest_path.exists() and read(manifest_path) != manifest:
        raise ValueError('frozen queue/proof/tool inputs changed; do not overwrite old evidence')
    atomic_write_json(manifest_path, manifest)
    records = []

    def run(command, log):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('w', encoding='utf-8') as stream:
            completed = subprocess.run([sys.executable, '-u', '-m'] + command, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=3600)
        if completed.returncode:
            raise RuntimeError('research attempt failed; preserve ' + str(log))

    try:
        for item in queue:
            name = item['strategy']
            admission = reuse_admissions.get(name, output / 'admissions' / name)
            contract_dir = next((directory for directory in reuse_contract_roots
                if (directory / 'artifacts' / name / 'contract.json').exists()), output / 'contracts' / name)
            completed = admission / 'FORMAL_COMPLETE.json'
            if completed.exists():
                record = completed_observation(admission, item, manifest, proof_hash)
            else:
                if admission.exists():
                    raise ValueError('partial financial attempt requires diagnosis, never blind replay: ' + str(admission))
                if not (contract_dir / 'artifacts' / name / 'contract.json').exists():
                    if contract_dir.exists():
                        raise ValueError('partial source contract requires diagnosis: ' + str(contract_dir))
                    run(['recovery.prepare_fit_risk_scope_contract', '--catalog-dir', str(args.catalog_dir),
                        '--indsvr-repo', str(args.indsvr_repo), '--sim-repo', str(args.sim_repo),
                        '--training-input-dir', str(args.training_input_dir), '--output-dir', str(contract_dir),
                        '--hypothesis', item['hypothesis'], '--symbol', item['symbol'], '--scene', item['scene']],
                        output / 'logs' / (name + '-contract.log'))
                run(['recovery.run_fit_risk_admission', '--contract-dir', str(contract_dir), '--strategy', name,
                    '--input-dir', str(args.input_dir), '--protocol', str(args.protocol), '--sim-repo', str(args.sim_repo),
                    '--oracle-dir', str(args.oracle_dir), '--output-dir', str(admission)], output / 'logs' / (name + '-financial.log'))
                record = completed_observation(admission, item, manifest, proof_hash)
            if any(record[key] != item[key] for key in ('strategy', 'symbol', 'scene', 'hypothesis', 'family')):
                raise ValueError('financial result does not match frozen queue scope')
            records.append(dict(record, admission_dir=str(admission), original_observation_reused=name in reuse_admissions))
            atomic_write_json(output / 'results.json', records)
            atomic_write_json(output / 'status.json', {'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'completed': len(records), 'total': len(queue), 'local_formal_qualified': sum(r['qualified'] for r in records),
                'published': 0, 'production_write': False})
            print('BALANCED_FIT_RISK', len(records), '/', len(queue), name, record['reason'], flush=True)
        atomic_write_json(output / 'BATCH_COMPLETE.json', {'manifest_sha256': sha(manifest_path),
            'completed': len(records), 'local_formal_qualified': sum(r['qualified'] for r in records), 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
