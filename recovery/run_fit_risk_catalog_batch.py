"""Frozen remaining-catalog research; excludes reserved/consumed cases, never publishes."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil

from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_scope_batch import SCENES, completed_observation, strategy_name
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha
from recovery.watch_fixed_primary_supplements import parent_alive


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def case_key(row):
    return row['symbol'], row['scene'], row['hypothesis']


def remaining_queue(catalog, symbols, excluded):
    """Each hypothesis rotates across every cell; no financial ranking or risk multiplication."""
    cells = [(symbol, scene) for symbol in sorted(symbols) for scene in SCENES]
    rows = []
    for turn in range(len(cells)):
        for index, row in enumerate(catalog):
            symbol, scene = cells[(turn + index) % len(cells)]
            item = dict(row, symbol=symbol, scene=scene,
                        strategy=strategy_name(symbol, scene, row['hypothesis']))
            if case_key(item) not in excluded:
                rows.append(item)
    if len({case_key(row) for row in rows}) != len(rows):
        raise ValueError('duplicate source scope in remaining queue')
    return rows


@contextmanager
def exclusive_batch(folder):
    """OS-held local process lock; a stale lock file alone is not an active process."""
    path = Path(folder) / 'runner.lock'
    with path.open('a+b') as stream:
        if not path.stat().st_size:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_status(path, value):
    # Operational I/O retry only; original financial helpers and their gates remain frozen.
    for attempt in range(8):
        try:
            atomic_write_json(path, value)
            return
        except PermissionError as error:
            if os.name != 'nt' or error.winerror not in (5, 32, 33) or attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


def source_parent_identity(pid, catalog_dir):
    process = psutil.Process(pid)
    command = process.cmdline()
    if ('-m' not in command or '--output-dir' not in command
            or command[command.index('-m') + 1] != 'recovery.verify_fit_risk_catalog'
            or Path(command[command.index('--output-dir') + 1]).resolve() != catalog_dir.resolve()
            or not process.is_running()):
        raise ValueError('source-proof parent process identity/output mismatch')
    return {'pid': pid, 'create_time': process.create_time(), 'command': command}


def resource_state(directory):
    free = shutil.disk_usage(directory).free
    memory = psutil.virtual_memory().available
    return {'ready': free >= 8 * 1024 ** 3 and memory >= 1536 * 1024 ** 2,
            'free_disk_bytes': free, 'available_memory_bytes': memory,
            'minimum_free_disk_bytes': 8 * 1024 ** 3, 'minimum_available_memory_bytes': 1536 * 1024 ** 2}


def verify_full_source_proof(directory):
    complete = read(directory / 'SOURCE_CONTRACT_COMPLETE.json')
    manifest = read(directory / 'manifest.json')
    expected = sha(directory / 'manifest.json')
    if (complete.get('completed') != 400 or complete.get('profile_cases') != 1600
            or complete.get('manifest_sha256') != expected
            or complete.get('financial_validation_started') is not False
            or complete.get('production_write') is not False or (directory / 'FAILED.json').exists()):
        raise ValueError('complete unmodified 400-source/1600-profile training proof required')
    rows = {row['hypothesis']: row for row in manifest['catalog']}
    found = {}
    for path in (directory / 'artifacts').glob('*/contract.json'):
        row = read(path)
        profiles = row['profiles']
        if (row['hypothesis'] not in rows or row['hypothesis'] in found
                or row['family'] != rows[row['hypothesis']]['family']
                or row['manifest_sha256'] != expected
                or sha(Path(row['artifact_path'])) != row['artifact_sha256']
                or sha(directory / 'frozen' / row['strategy'] / 'GeneratedStrategy.java') != row['source_sha256']
                or row.get('source_validator_passed') is not True
                or [p['risk_profile'] for p in profiles] != [0, 1, 2, 3]
                or any(p['bars'] != 35040 or p['mismatches'] != 0 for p in profiles)):
            raise ValueError('source/artifact/profile training proof changed: ' + str(path))
        found[row['hypothesis']] = sha(path)
    if len(found) != 400:
        raise ValueError('missing full catalog source contracts')
    return {'manifest_sha256': expected, 'completion_sha256': sha(directory / 'SOURCE_CONTRACT_COMPLETE.json'),
            'contracts_sha256': found, 'financial_validation_started': False, 'production_write': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('catalog-dir', 'indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir',
                 'protocol', 'oracle-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--exclude-queue', type=Path, action='append', required=True)
    parser.add_argument('--exclude-admission', type=Path, action='append', default=[])
    parser.add_argument('--wait-for-catalog-pid', type=int)
    args = parser.parse_args()
    for name in ('catalog_dir', 'indsvr_repo', 'sim_repo', 'training_input_dir', 'input_dir',
                 'protocol', 'oracle_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(output):
        if (output / 'FAILED.json').exists():
            raise ValueError('preserve and diagnose the previous failure before resuming')
        catalog = read(args.catalog_dir / 'manifest.json')
        rows = catalog['catalog']
        if (len(rows) != 400 or len({row['hypothesis'] for row in rows}) != 400
                or len({row['family'] for row in rows}) != 202):
            raise ValueError('original frozen 400-direction/202-class policy required')
        native = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
        if (catalog['source_sha256']['StrategyResearchBatchCli'] != sha(native)
                or catalog['exporter_sha256'] != sha(Path(__file__).with_name('export_representative_candidate.py'))):
            raise ValueError('pre-financial catalog source/exporter changed')
        proof_hash = require_proof(args.oracle_dir, Path(__file__).with_name('java'), args.sim_repo)
        ready = read(args.input_dir / 'READY.json')
        protocol = read(args.protocol)
        if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'fit_only_risk_v1'
                or protocol.get('risk_profiles') != [0, 1, 2, 3] or len(ready['symbols']) != 10):
            raise ValueError('unchanged existing temporal four-profile policy/data required')
        bindings = {'protocol_sha256': sha(args.protocol), 'ready_sha256': sha(args.input_dir / 'READY.json')}
        known = {row['hypothesis']: row for row in rows}
        excluded, reservations, observations = set(), {}, {}
        for path in args.exclude_queue:
            path = path.resolve()
            queue = read(path)
            if (queue['catalog_sha256'] != sha(args.catalog_dir / 'manifest.json')
                    or any(queue[key] != value for key, value in bindings.items())):
                raise ValueError('reserved queue policy/data/catalog mismatch')
            for item in queue['queue']:
                if (item['hypothesis'] not in known or known[item['hypothesis']]['family'] != item['family']
                        or item['strategy'] != strategy_name(*case_key(item))):
                    raise ValueError('reserved queue scope/source mismatch')
                excluded.add(case_key(item))
            reservations[str(path)] = sha(path)
        for directory in args.exclude_admission:
            directory = directory.resolve()
            result = read(directory / 'results.json')[0]
            item = {key: result[key] for key in ('strategy', 'symbol', 'scene', 'hypothesis', 'family')}
            if (item['hypothesis'] not in known or known[item['hypothesis']]['family'] != item['family']
                    or item['strategy'] != strategy_name(*case_key(item))):
                raise ValueError('previous observation source/scope mismatch')
            completed_observation(directory, item, bindings, proof_hash)
            excluded.add(case_key(item))
            observations[str(directory)] = {path.name: sha(path) for path in directory.glob('*.json')}
        queue = remaining_queue(rows, ready['symbols'], excluded)
        plan_path = output / 'plan.json'
        previous = read(plan_path) if plan_path.exists() else None
        parent = previous.get('catalog_parent_identity') if previous else None
        if args.wait_for_catalog_pid:
            if previous and (not parent or parent['pid'] != args.wait_for_catalog_pid):
                raise ValueError('bound catalog parent changed')
            if not previous:
                parent = source_parent_identity(args.wait_for_catalog_pid, args.catalog_dir)
        elif parent:
            raise ValueError('resume with the original parent binding argument')
        tool_names = ('run_fit_risk_catalog_batch.py', 'run_fit_risk_scope_batch.py',
                      'prepare_fit_risk_scope_contract.py', 'run_fit_risk_admission.py',
                      'export_representative_candidate.py', 'watch_fixed_primary_supplements.py')
        plan = dict(bindings, schema='frozen_remaining_fit_risk_catalog_v1', queue=queue,
            catalog_sha256=sha(args.catalog_dir / 'manifest.json'),
            training_ready_sha256=sha(args.training_input_dir / 'READY.json'),
            oracle_manifest_sha256=proof_hash, catalog_parent_identity=parent,
            reserved_queue_sha256=reservations, excluded_observation_sha256=observations,
            unique_reserved_or_consumed_scopes=len(excluded),
            tool_sha256={name: sha(Path(__file__).with_name(name)) for name in tool_names},
            selection='whole_remaining_pre_frozen_catalog_no_financial_ranking_cell_rotation',
            policy='four_fit_selected_profiles_are_one_policy_not_four_independent_strategies',
            server_codegen_allowed=False, production_write=False)
        if previous != plan and previous is not None:
            raise ValueError('frozen remaining queue or research evidence changed')
        if previous is None:
            write_status(plan_path, plan)
        plan_hash = sha(plan_path)
        records = []
        try:
            print('FROZEN_REMAINING_QUEUE', len(queue), 'excluded', len(excluded), 'plan', plan_hash, flush=True)
            while not (args.catalog_dir / 'SOURCE_CONTRACT_COMPLETE.json').exists():
                if ((args.catalog_dir / 'FAILED.json').exists() or parent is None or not parent_alive(parent)):
                    raise ValueError('source proof not complete and bound parent failed/ended')
                write_status(output / 'status.json', {'state': 'WAITING_FOR_SOURCE_PROOF', 'completed': 0,
                    'total': len(queue), 'local_formal_qualified': 0, 'parent_pid': parent['pid'],
                    'production_write': False})
                time.sleep(10)
            source_proof = verify_full_source_proof(args.catalog_dir)
            proof_path = output / 'engineering-proof.json'
            if proof_path.exists() and read(proof_path) != source_proof:
                raise ValueError('completed engineering evidence changed')
            if not proof_path.exists():
                write_status(proof_path, source_proof)
            for item in queue:
                resources = resource_state(output)
                while not resources['ready']:
                    write_status(output / 'status.json', {'state': 'WAITING_FOR_LOCAL_RESOURCES',
                        'completed': len(records), 'total': len(queue), 'local_formal_qualified': sum(r['qualified'] for r in records),
                        'resources': resources, 'production_write': False})
                    time.sleep(10)
                    resources = resource_state(output)
                name = item['strategy']
                admission = output / 'admissions' / name
                contract = (args.catalog_dir if item['symbol'] == 'BTCUSDT' and item['scene'] == 'trend'
                            else output / 'contracts' / name)
                if not (admission / 'FORMAL_COMPLETE.json').exists():
                    if admission.exists():
                        raise ValueError('partial financial attempt: diagnose without replay: ' + str(admission))
                    if not (contract / 'artifacts' / name / 'contract.json').exists():
                        if contract.exists():
                            raise ValueError('partial source contract requires diagnosis: ' + str(contract))
                        run_module(['recovery.prepare_fit_risk_scope_contract', '--catalog-dir', str(args.catalog_dir),
                            '--indsvr-repo', str(args.indsvr_repo), '--sim-repo', str(args.sim_repo),
                            '--training-input-dir', str(args.training_input_dir), '--output-dir', str(contract),
                            '--hypothesis', item['hypothesis'], '--symbol', item['symbol'], '--scene', item['scene']],
                            output / 'logs' / (name + '-contract.log'))
                    run_module(['recovery.run_fit_risk_admission', '--contract-dir', str(contract), '--strategy', name,
                        '--input-dir', str(args.input_dir), '--protocol', str(args.protocol), '--sim-repo', str(args.sim_repo),
                        '--oracle-dir', str(args.oracle_dir), '--output-dir', str(admission)],
                        output / 'logs' / (name + '-financial.log'))
                record = completed_observation(admission, item, bindings, proof_hash)
                contract_file = contract / 'artifacts' / name / 'contract.json'
                contract_record = read(contract_file)
                admission_manifest = read(admission / 'manifest.json')
                if (sha(contract_file) != admission_manifest['contract_sha256']
                        or sha(Path(contract_record['artifact_path'])) != admission_manifest['artifact_sha256']
                        or contract_record['source_sha256'] != record['source_sha256']):
                    raise ValueError('completed source/artifact contract changed')
                records.append(dict(record, admission_dir=str(admission)))
                write_status(output / 'results.json', records)
                write_status(output / 'status.json', {'state': 'RUNNING', 'updated_utc': datetime.now(timezone.utc).isoformat(),
                    'completed': len(records), 'total': len(queue), 'local_formal_qualified': sum(r['qualified'] for r in records),
                    'published': 0, 'production_write': False})
                print('REMAINING_FIT_RISK', len(records), '/', len(queue), name, record['reason'], flush=True)
            write_status(output / 'BATCH_COMPLETE.json', {'plan_sha256': plan_hash,
                'completed': len(records), 'local_formal_qualified': sum(r['qualified'] for r in records),
                'results_sha256': sha(output / 'results.json'), 'production_write': False})
        except Exception as error:
            write_status(output / 'FAILED.json', {'completed': len(records), 'error': str(error),
                'plan_sha256': plan_hash, 'production_write': False})
            raise


def run_module(arguments, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('x', encoding='utf-8') as stream:
        result = subprocess.run([sys.executable, '-u', '-m'] + arguments, stdout=stream,
            stderr=subprocess.STDOUT, timeout=3600)
    if result.returncode:
        raise RuntimeError('research execution failed; preserve ' + str(log))


if __name__ == '__main__':
    main()
