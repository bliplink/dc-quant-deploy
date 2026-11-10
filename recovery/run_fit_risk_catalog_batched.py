"""Checkpoint-preserving local controller: same frozen full queue/financial CLI, batched training only."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import sys
import threading
import time

import psutil

from recovery.prepare_fit_risk_scope_contract_batched import require_batching_proof
from recovery.research_control_handoff import drain_and_stop, require_local_research_parent, identity
from recovery.run_fit_risk_admission import require_proof
from recovery.local_strategy_backtest import build_parameters
from recovery.run_fit_risk_catalog_batch import (
    case_key, exclusive_batch, read, remaining_queue, resource_state, verify_full_source_proof, write_status)
from recovery.run_fit_risk_scope_batch import completed_observation, strategy_name
from recovery.strict_primary_admission import adjudicate_primary
from recovery.temporal_admission_contract import require_temporally_isolated_admission
from recovery.verify_fit_only_risk_contract import sha
from recovery.watch_fixed_primary_supplements import parent_alive


def validate_queue(plan, catalog, symbols, exclusions):
    queue = plan['queue']
    if (plan.get('schema') != 'frozen_remaining_fit_risk_catalog_v1'
            or plan.get('server_codegen_allowed') is not False or plan.get('production_write') is not False
            or len(queue) != 19599 or len(catalog) != 400
            or len({row['hypothesis'] for row in catalog}) != 400
            or len({row['family'] for row in catalog}) != 202
            or len({case_key(row) for row in queue}) != len(queue)
            or any(row['strategy'] != strategy_name(*case_key(row)) for row in queue)
            or queue != remaining_queue(catalog, symbols, exclusions)):
        raise ValueError('exact original unranked full queue/exclusions required')


def contract_folder(args, item):
    return (args.catalog_dir if item['symbol'] == 'BTCUSDT' and item['scene'] == 'trend'
            else args.legacy_dir / 'contracts' / item['strategy'])


def verify_contract(args, item):
    folder = contract_folder(args, item)
    path = folder / 'artifacts' / item['strategy'] / 'contract.json'
    record = read(path)
    profiles = record['profiles']
    if (record['manifest_sha256'] != sha(folder / 'manifest.json')
            or record['hypothesis'] != item['hypothesis'] or record['family'] != item['family']
            or record['strategy'] != item['strategy'] or record.get('source_validator_passed') is not True
            or record['source_sha256'] != sha(folder / 'frozen' / item['strategy'] / 'GeneratedStrategy.java')
            or record['artifact_sha256'] != sha(Path(record['artifact_path']))
            or [row['risk_profile'] for row in profiles] != [0, 1, 2, 3]
            or any(row['bars'] != 35040 or row['mismatches'] != 0 for row in profiles)):
        raise ValueError('complete unchanged source/profile contract required: ' + item['strategy'])
    if folder != args.catalog_dir:
        manifest = read(folder / 'manifest.json')
        complete = read(folder / 'SOURCE_CONTRACT_COMPLETE.json')
        if (complete['manifest_sha256'] != sha(folder / 'manifest.json')
                or complete.get('completed') != 1 or complete.get('profile_cases') != 4
                or manifest['symbol'] != item['symbol'] or manifest['scene'] != item['scene']
                or manifest['parent_catalog_sha256'] != sha(args.catalog_dir / 'manifest.json')):
            raise ValueError('scoped contract identity/completion changed')
    return path, record


def verified_observation(args, item, plan, oracle):
    admission = args.legacy_dir / 'admissions' / item['strategy']
    record = completed_observation(admission, item, plan, oracle)
    path, contract = verify_contract(args, item)
    manifest = read(admission / 'manifest.json')
    if (manifest['contract_sha256'] != sha(path) or manifest['artifact_sha256'] != contract['artifact_sha256']
            or contract['source_sha256'] != record['source_sha256']):
        raise ValueError('completed admission is not bound to its exact source artifact')
    source_seed = read(path.parent.parent.parent / 'frozen' / item['strategy'] / 'seed.json')
    admission_seed = read(admission / 'frozen' / item['strategy'] / 'seed.json')
    spec = read(admission / 'validation-spec.json')
    if (source_seed != admission_seed
            or spec['candidateParameters'] != build_parameters(source_seed['strategies'][0]['request'])):
        raise ValueError('original fitted parameter policy changed after financial replay')
    strict = None
    if record['qualified']:
        envelope = read(Path(record['result_path']))
        require_temporally_isolated_admission(envelope, require_risk_profile=True)
        seed = read(admission / 'frozen' / item['strategy'] / 'seed.json')
        strict = adjudicate_primary(envelope['result'], seed['strategies'][0]['request'].get('optimizationProfile'))
    return dict(record, admission_dir=str(admission), strict_local_qualified=bool(strict and strict['qualified']),
                strict_admission=strict)


def scan_checkpoint(args, plan, oracle):
    """Only immutable per-case files; never read a concurrently replaced aggregate ledger."""
    by_name = {row['strategy']: row for row in plan['queue']}
    records, hashes = {}, {}
    for folder in (args.legacy_dir / 'admissions').glob('*'):
        if not folder.is_dir():
            continue
        if folder.name not in by_name or not (folder / 'FORMAL_COMPLETE.json').exists():
            raise ValueError('partial/unknown financial attempt; never replay: ' + str(folder))
        records[folder.name] = verified_observation(args, by_name[folder.name], plan, oracle)
        hashes[folder.name] = {name: sha(folder / name) for name in ('manifest.json', 'FORMAL_COMPLETE.json', 'results.json')}
    for folder in (args.legacy_dir / 'contracts').glob('*'):
        if not folder.is_dir():
            continue
        if folder.name not in by_name:
            raise ValueError('source scope outside frozen queue')
        verify_contract(args, by_name[folder.name])
    return {'completed': len(records), 'records': records, 'checkpoint_sha256': hashes,
            'financial_replay_performed': False, 'production_write': False}


def require_context(args):
    plan = read(args.legacy_dir / 'plan.json')
    catalog = read(args.catalog_dir / 'manifest.json')
    ready = read(args.input_dir / 'READY.json')
    research = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    if sha(research) != catalog['source_sha256']['StrategyResearchBatchCli']:
        raise ValueError('frozen native source changed')
    for name, digest in catalog['research_class_sha256'].items():
        if sha(class_dir / name) != digest:
            raise ValueError('frozen research bytecode changed: ' + name)
    for name, digest in plan['tool_sha256'].items():
        if sha(Path(__file__).with_name(name)) != digest:
            raise ValueError('original frozen tool changed: ' + name)
    for key, path in (('protocol_sha256', args.protocol), ('ready_sha256', args.input_dir / 'READY.json'),
                      ('training_ready_sha256', args.training_input_dir / 'READY.json'),
                      ('catalog_sha256', args.catalog_dir / 'manifest.json')):
        if sha(path) != plan[key]:
            raise ValueError('original frozen input changed: ' + key)
    exclusions = set()
    for path, digest in plan['reserved_queue_sha256'].items():
        if sha(Path(path)) != digest:
            raise ValueError('reserved queue changed')
        exclusions.update(case_key(row) for row in read(Path(path))['queue'])
    for directory, expected in plan['excluded_observation_sha256'].items():
        folder = Path(directory)
        if any(sha(folder / name) != digest for name, digest in expected.items()):
            raise ValueError('excluded consumed observation changed')
        exclusions.update(case_key(row) for row in read(folder / 'results.json'))
    validate_queue(plan, catalog['catalog'], ready['symbols'], exclusions)
    if verify_full_source_proof(args.catalog_dir) != read(args.legacy_dir / 'engineering-proof.json'):
        raise ValueError('full source proof changed')
    oracle = require_proof(args.oracle_dir, Path(__file__).with_name('java'), args.sim_repo)
    if oracle != plan['oracle_manifest_sha256']:
        raise ValueError('original financial oracle changed')
    batching = require_batching_proof(args.batching_proof_dir, args.catalog_dir, args.training_input_dir, args.indsvr_repo)
    return plan, oracle, batching


def run_queue(args, plan, oracle, checkpoint):
    records = dict(checkpoint['records'])
    pending = [row for row in plan['queue'] if row['strategy'] not in records]
    active, stages, mutex = {}, {}, threading.Lock()
    errors, cursor = [], 0

    def run_module(item, module_args, stage):
        path = args.output_dir / 'logs' / (item['strategy'] + '-' + stage + '.log')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            process = subprocess.Popen([sys.executable, '-u', '-m'] + module_args, stdout=stream,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            with mutex:
                stages[item['strategy']] = dict(identity(psutil.Process(process.pid)), stage=stage)
            # Do not kill a calculation merely because observation is slow.
            code = process.wait()
            with mutex:
                stages.pop(item['strategy'], None)
            if code:
                raise ValueError('preserve failed ' + stage + ' attempt: ' + str(path))

    def calculate(item):
        name = item['strategy']
        admission = args.legacy_dir / 'admissions' / name
        if admission.exists():
            raise ValueError('unexpected partial financial scope; never repeat: ' + name)
        folder = contract_folder(args, item)
        if not (folder / 'artifacts' / name / 'contract.json').exists():
            if folder.exists():
                raise ValueError('partial source scope; preserve for diagnosis: ' + str(folder))
            run_module(item, ['recovery.prepare_fit_risk_scope_contract_batched', '--catalog-dir', str(args.catalog_dir),
                '--indsvr-repo', str(args.indsvr_repo), '--sim-repo', str(args.sim_repo),
                '--training-input-dir', str(args.training_input_dir), '--batching-proof-dir', str(args.batching_proof_dir),
                '--output-dir', str(folder), '--hypothesis', item['hypothesis'], '--symbol', item['symbol'],
                '--scene', item['scene']], 'contract')
        verify_contract(args, item)
        run_module(item, ['recovery.run_fit_risk_admission', '--contract-dir', str(folder), '--strategy', name,
            '--input-dir', str(args.input_dir), '--protocol', str(args.protocol), '--sim-repo', str(args.sim_repo),
            '--oracle-dir', str(args.oracle_dir), '--output-dir', str(admission)], 'financial')
        return verified_observation(args, item, plan, oracle)

    def save(state):
        with mutex:
            workers = dict(stages)
        write_status(args.output_dir / 'status.json', {'state': state,
            'updated_utc': datetime.now(timezone.utc).isoformat(), 'completed': len(records), 'total': len(plan['queue']),
            'raw_local_qualified': sum(r['qualified'] for r in records.values()),
            'strict_local_qualified': sum(r['strict_local_qualified'] for r in records.values()),
            'active_workers': workers, 'errors': errors, 'published': 0, 'production_write': False})

    def save_records():
        ordered = [records[row['strategy']] for row in plan['queue'] if row['strategy'] in records]
        write_status(args.output_dir / 'results.json', ordered)

    save_records()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while cursor < len(pending) or active:
            while not errors and cursor < len(pending) and len(active) < args.workers:
                resources = resource_state(args.legacy_dir)
                if not resources['ready'] or resources['available_memory_bytes'] < (1536 + 768 * len(active)) * 1024 ** 2:
                    break
                item = pending[cursor]
                active[pool.submit(calculate, item)] = item
                cursor += 1
            save('DRAINING_AFTER_ERROR' if errors else ('RUNNING' if active else 'WAITING_FOR_LOCAL_RESOURCES'))
            if not active:
                if errors:
                    break
                time.sleep(2)
                continue
            finished, _ = wait(active, timeout=2, return_when=FIRST_COMPLETED)
            for future in finished:
                item = active.pop(future)
                try:
                    result = future.result()
                    if result['strategy'] in records:
                        raise ValueError('duplicate completed financial observation')
                    records[result['strategy']] = result
                    write_status(args.output_dir / 'adjudications' / (result['strategy'] + '.json'), result)
                    print('BATCHED_CATALOG', len(records), '/', len(plan['queue']), result['strategy'],
                          result['reason'], 'strict', result['strict_local_qualified'], flush=True)
                except Exception as error:
                    errors.append({'strategy': item['strategy'], 'error': str(error)})
            if finished:
                save_records()
        save('FAILED' if errors else 'COMPLETE')
    if errors:
        write_status(args.output_dir / 'FAILED.json', {'errors': errors, 'completed': len(records), 'production_write': False})
        raise ValueError('local execution failed; preserve every completed and partial attempt')
    write_status(args.output_dir / 'BATCH_COMPLETE.json', {'original_plan_sha256': sha(args.legacy_dir / 'plan.json'),
        'controller_manifest_sha256': sha(args.output_dir / 'manifest.json'), 'completed': len(records),
        'results_sha256': sha(args.output_dir / 'results.json'), 'production_write': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('legacy-dir', 'catalog-dir', 'indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir',
                 'protocol', 'oracle-dir', 'batching-proof-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--handoff-pid', type=int)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    for name in ('legacy_dir', 'catalog_dir', 'indsvr_repo', 'sim_repo', 'training_input_dir', 'input_dir',
                 'protocol', 'oracle_dir', 'batching_proof_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.legacy_dir == args.output_dir or args.legacy_dir in args.output_dir.parents or args.output_dir in args.legacy_dir.parents:
        raise ValueError('controller and original evidence roots must be separate siblings')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(args.output_dir):
        if (args.output_dir / 'FAILED.json').exists() or (args.legacy_dir / 'FAILED.json').exists():
            raise ValueError('preserve previous failure; diagnose before resuming')
        plan, oracle, batching = require_context(args)
        manifest_path = args.output_dir / 'manifest.json'
        previous = read(manifest_path) if manifest_path.exists() else None
        parent = previous['original_parent'] if previous else require_local_research_parent(args.handoff_pid, args.legacy_dir)
        if args.handoff_pid is not None and parent['pid'] != args.handoff_pid:
            raise ValueError('original parent binding changed')
        tool_names = ('run_fit_risk_catalog_batched.py', 'research_control_handoff.py',
                      'prepare_fit_risk_scope_contract_batched.py', 'verify_batched_fit_risk_parity.py',
                      'strict_primary_admission.py', 'temporal_admission_contract.py')
        manifest = {'schema': 'full_catalog_checkpoint_handoff_controller_v1', 'original_parent': parent,
            'original_plan_sha256': sha(args.legacy_dir / 'plan.json'), 'oracle_manifest_sha256': oracle,
            'batching_proof_manifest_sha256': batching, 'workers': args.workers,
            'paths': {name: str(getattr(args, name)) for name in ('legacy_dir', 'catalog_dir', 'indsvr_repo', 'sim_repo',
                'training_input_dir', 'input_dir', 'protocol', 'oracle_dir', 'batching_proof_dir', 'output_dir')},
            'tool_sha256': {name: sha(Path(__file__).with_name(name)) for name in tool_names},
            'policy': 'unchanged_original_queue_financial_cli_and_checkpoints_no_financial_reruns',
            'server_codegen_allowed': False, 'production_write': False}
        if previous is not None and previous != manifest:
            raise ValueError('controller source/proof/arguments changed; preserve frozen attempt')
        if previous is None:
            write_status(manifest_path, manifest)
        if args.prepare_only:
            print('CONTROLLER_PREPARED', len(plan['queue']), 'workers', args.workers, 'no process mutations', flush=True)
            return
        if args.resume:
            if parent_alive(parent) or read(args.output_dir / 'HANDOFF_INTENT.json')['phase'] != 'TRANSFERRED':
                raise ValueError('resume requires a fully transferred, absent original parent')
        else:
            drain_and_stop(parent, args.output_dir, lambda: scan_checkpoint(args, plan, oracle))
        with exclusive_batch(args.legacy_dir):
            checkpoint = scan_checkpoint(args, plan, oracle)
            write_status(args.legacy_dir / 'CONTROL_HANDOFF.json', {'controller_dir': str(args.output_dir),
                'controller_manifest_sha256': sha(manifest_path), 'original_plan_sha256': manifest['original_plan_sha256'],
                'initial_checkpoint_count': checkpoint['completed'], 'original_parent': parent,
                'children_stopped': False, 'production_write': False})
            print('CONTROL_TRANSFERRED', checkpoint['completed'], 'immutable financial observations reused', flush=True)
            run_queue(args, plan, oracle, checkpoint)


if __name__ == '__main__':
    main()
