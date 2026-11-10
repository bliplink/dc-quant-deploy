"""Move an unexecuted clock queue to one memory-guarded local slot; never changes finance."""
import argparse
from argparse import Namespace
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import time

import psutil

from recovery.local_strategy_backtest import java_classpath
from recovery.run_directional_clock_batch import SCOPE_FIELDS, export_source, frozen_queue, require_hashes
from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_catalog_batch import exclusive_batch, resource_state, write_status
from recovery.run_ohlcv_profile_proxy_batch import run_case
from recovery.run_true_adx_batch import read
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute

MINIMUM_EXTRA_SLOT_MEMORY_MIB = 3072
ORIGINAL_MODULE = 'recovery.run_directional_clock_batch'
CONTEXT_PATHS = ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir',
                 'protocol', 'engineering-dir', 'regression-dir', 'fit-oracle-dir', 'locked-oracle-dir')


def option(command, key):
    token = '--' + key
    if command.count(token) != 1:
        raise ValueError('one exact original command option required: ' + token)
    index = command.index(token)
    if index + 1 >= len(command): raise ValueError('missing original option value')
    return command[index + 1]


def original_context(command, original_dir):
    if '-m' not in command or command[command.index('-m') + 1] != ORIGINAL_MODULE:
        raise ValueError('only the original local clock waiter can migrate')
    if Path(option(command, 'output-dir')).resolve() != original_dir:
        raise ValueError('original command output scope changed')
    return Namespace(**{name.replace('-', '_'): Path(option(command, name)).resolve() for name in CONTEXT_PATHS})


def require_zero_finance(original_dir, manifest_sha):
    if sha(original_dir / 'manifest.json') != manifest_sha:
        raise ValueError('original frozen plan changed')
    manifest, status = read(original_dir / 'manifest.json'), read(original_dir / 'status.json')
    if (manifest.get('schema') != 'frozen_directional_clock_100_scopes_v1'
            or len(manifest.get('queue', [])) != 100 or len({r['strategy'] for r in manifest['queue']}) != 100
            or status.get('state') != 'WAITING_FOR_BOUND_PROFILE_BATCH'
            or status.get('completed') != 0 or status.get('total') != 100):
        raise ValueError('only a genuinely zero-dispatch waiting plan can migrate')
    forbidden = ('candidates', 'frozen', 'classes', 'results.json', 'FAILED.json', 'FORMAL_COMPLETE.json')
    if any((original_dir / name).exists() for name in forbidden) or list(original_dir.rglob('*STARTED.json')):
        raise ValueError('source/financial work already started; never migrate or replay it here')
    return manifest, status


def observe_idle(original_dir, manifest_sha, pid, create_time):
    manifest, status = require_zero_finance(original_dir, manifest_sha)
    process = psutil.Process(pid)
    if process.create_time() != create_time:
        raise ValueError('waiting PID was reused')
    command = process.cmdline(); original_context(command, original_dir)
    children = [p for p in process.children(recursive=True) if p.name().lower() in ('python.exe', 'java.exe', 'javac.exe')]
    if children:
        raise ValueError('waiting process has a calculation child; do not stop it')
    parent = manifest['parent_identity']; owner = psutil.Process(parent['pid'])
    if owner.create_time() != parent['create_time'] or owner.cmdline() != parent['command']:
        raise ValueError('bound profile parent identity changed')
    parent_dir = Path(parent['output_dir']); parent_status = read(parent_dir / 'status.json')
    if (int(parent_status.get('completed', 200)) >= 200 or (parent_dir / 'FORMAL_COMPLETE.json').exists()
            or (parent_dir / 'FAILED.json').exists()):
        raise ValueError('parent may release or fail the waiter; preserve and re-audit')
    return process, manifest, status


def map_frozen_tools(original):
    """Every used Python/helper copy must retain the original bytes, not just equivalent logic."""
    local = Path(__file__).parent; used = {}
    for filename, digest in original['tool_sha256'].items():
        old = Path(filename)
        if sha(old) != digest: raise ValueError('original frozen dependency changed: ' + filename)
        if old.suffix == '.py': actual = local / old.name
        elif old.suffix == '.java': actual = local / 'java' / old.name
        else: actual = old  # The actual protocol path stays on its original immutable view.
        if sha(actual) != digest: raise ValueError('used dependency differs from original bytes: ' + str(actual))
        used[str(actual)] = digest
    used[str(Path(__file__))] = sha(Path(__file__))
    return used


def verify_context(context, original):
    used = map_frozen_tools(original)
    require_hashes(original['source_sha256']); require_hashes(original['classes_sha256'])
    java_dir = Path(__file__).with_name('java')
    proof = require_proof(context.fit_oracle_dir, java_dir, context.sim_repo)
    if proof != original['fit_oracle_manifest_sha256']: raise ValueError('original actual FIT proof changed')
    locked = read(context.locked_oracle_dir / 'audit.json')
    locked_manifest = read(context.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != original['locked_oracle_manifest_sha256']
            or sha(context.locked_oracle_dir / 'manifest.json') != original['locked_oracle_manifest_sha256']
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('original locked-holdout proof changed')
    engineering = read(context.engineering_dir / 'manifest.json')
    complete = read(context.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json')
    regression = read(context.regression_dir / 'audit.json')
    if (sha(context.engineering_dir / 'manifest.json') != original['engineering_manifest_sha256']
            or complete['manifest_sha256'] != original['engineering_manifest_sha256']
            or complete.get('completed') != 2 or complete.get('mathematics_tests') != 16
            or complete.get('independent_path_fixtures') != 64
            or complete.get('financial_validation_started') is not False
            or sha(context.regression_dir / 'manifest.json') != original['regression_manifest_sha256']
            or regression.get('state') != 'complete'
            or regression['manifest_sha256'] != original['regression_manifest_sha256']
            or regression['regression_log_sha256'] != sha(context.regression_dir / 'full-research-regression.log')):
        raise ValueError('original nonzero-source engineering/regression evidence changed')
    reference = context.reference_indsvr_repo
    if (sha(reference / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class') != engineering['source_validator_class_sha256']
            or sha(reference / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class') != engineering['original_parity_cli_sha256']):
        raise ValueError('original validator/parity CLI changed')
    ready, training = read(context.input_dir / 'READY.json'), read(context.training_input_dir / 'READY.json')
    if (sha(context.input_dir / 'READY.json') != original['ready_sha256']
            or sha(context.training_input_dir / 'READY.json') != original['training_ready_sha256']
            or ready['protocol_sha256'] != sha(context.protocol)
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('original protocol/market/training views changed')
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(context.input_dir / (symbol + suffix)) != ready['files'][symbol][key]:
                raise ValueError('original financial market bytes changed')
        if sha(context.training_input_dir / (symbol + '-15m.tsv')) != training['files'][symbol]['bars_sha256']:
            raise ValueError('original training bytes changed')
    native = context.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/DirectionalClockStrategy.java'
    if frozen_queue(native.read_text(encoding='utf-8'), ready['symbols']) != original['queue']:
        raise ValueError('same entire100-scope queue required, not a smaller shortlist')
    return used, ready, read(context.protocol)


def extra_slot_resources(output, minimum_memory):
    if minimum_memory < MINIMUM_EXTRA_SLOT_MEMORY_MIB:
        raise ValueError('the extra slot cannot lower its3GiB memory guard')
    resources = resource_state(output)
    available = psutil.virtual_memory().available // 1048576
    cores = psutil.cpu_count() or 0
    return dict(resources, extra_slot_memory_mib=available, minimum_extra_slot_memory_mib=minimum_memory,
                logical_cores=cores, ready=bool(resources['ready'] and available >= minimum_memory and cores >= 4))


def require_old_owner_stopped(record):
    identity = record['old_identity']
    if psutil.pid_exists(identity['pid']):
        owner = psutil.Process(identity['pid'])
        if owner.create_time() == identity['create_time']:
            raise ValueError('original waiter still lives; cannot dispatch a second owner')
    if (record.get('schema') != 'zero_finance_clock_scheduling_handoff_v1'
            or record.get('original_completed') != 0 or record.get('calculation_children') != []
            or record.get('financial_dispatch_ever_started') is not False
            or record.get('old_owner_stop_verified') is not True):
        raise ValueError('explicit zero-finance retirement proof required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-wait-dir', type=Path, required=True)
    parser.add_argument('--original-manifest-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--minimum-free-memory-mib', type=int, default=MINIMUM_EXTRA_SLOT_MEMORY_MIB)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--waiting-pid', type=int)
    parser.add_argument('--waiting-create-time', type=float)
    args = parser.parse_args(); original_dir, output = args.original_wait_dir.resolve(), args.output_dir.resolve()
    if original_dir == output: raise ValueError('use a distinct output; preserve the original unexecuted plan')
    if args.minimum_free_memory_mib < MINIMUM_EXTRA_SLOT_MEMORY_MIB: parser.error('minimum memory must be at least3072MiB')
    original, _ = require_zero_finance(original_dir, args.original_manifest_sha256)
    if args.prepare_only:
        if output.exists(): raise ValueError('fresh prepare-only directory required')
        process, _, _ = observe_idle(original_dir, args.original_manifest_sha256, args.waiting_pid, args.waiting_create_time)
        command = process.cmdline(); handoff = None
    else:
        handoff = read(original_dir / 'ORCHESTRATION_HANDOFF.json'); require_old_owner_stopped(handoff)
        if (handoff['original_manifest_sha256'] != args.original_manifest_sha256
                or Path(handoff['target_output_dir']).resolve() != output
                or handoff['controller_source_sha256'] != sha(Path(__file__))):
            raise ValueError('handoff controller/source/target scope changed')
        command = handoff['old_identity']['command']
    context = original_context(command, original_dir)
    used, ready, protocol = verify_context(context, original)
    resources = extra_slot_resources(output.parent, args.minimum_free_memory_mib)
    if args.prepare_only:
        output.mkdir(parents=True)
        write_status(output / 'PREPARE_COMPLETE.json', dict(original_manifest_sha256=args.original_manifest_sha256,
            controller_source_sha256=sha(Path(__file__)), source_and_helpers_unchanged=True, entire_queue_scopes=100,
            retirer_source_sha256=sha(Path(__file__).with_name('retire_directional_clock_waiter.py')),
            checked_tool_sha256=used, resources=resources, financial_dispatch_started=False, production_write=False))
        print('PARALLEL_CLOCK_PREPARED', resources, flush=True); return
    output.mkdir(parents=True, exist_ok=True)
    # Holding the original lock also blocks accidental revival of its old waiting command.
    with exclusive_batch(original_dir), exclusive_batch(output):
        if (output / 'FAILED.json').exists(): raise ValueError('preserve the prior failure; never blind replay')
        manifest = dict(schema='frozen_directional_clock_parallel_100_scopes_v1', queue=original['queue'],
            original_wait_dir=str(original_dir), original_manifest_sha256=args.original_manifest_sha256,
            handoff_sha256=sha(original_dir / 'ORCHESTRATION_HANDOFF.json'), used_tool_sha256=used,
            source_sha256=original['source_sha256'], classes_sha256=original['classes_sha256'],
            ready_sha256=original['ready_sha256'], training_ready_sha256=original['training_ready_sha256'],
            fit_oracle_manifest_sha256=original['fit_oracle_manifest_sha256'], locked_oracle_manifest_sha256=original['locked_oracle_manifest_sha256'],
            minimum_extra_slot_memory_mib=args.minimum_free_memory_mib, added_serial_slots=1,
            financial_rules_changed=False, source_policy_changed=False, earlier_financial_results_replayed=False,
            mechanism_group=original['mechanism_group'], server_codegen_allowed=False, production_write=False)
        if (output / 'manifest.json').exists() and read(output / 'manifest.json') != manifest:
            raise ValueError('parallel frozen manifest changed')
        if not (output / 'manifest.json').exists(): write_status(output / 'manifest.json', manifest)
        manifest_hash = sha(output / 'manifest.json'); records = []; context.output_dir = output
        try:
            while not resources['ready']:
                write_status(output / 'status.json', dict(state='WAITING_FOR_EXTRA_SLOT_RESOURCES', completed=0, total=100,
                    resources=resources, production_write=False));time.sleep(10)
                resources = extra_slot_resources(output, args.minimum_free_memory_mib)
            classes = output / 'classes'; classes.mkdir(exist_ok=True)
            helpers = [Path(__file__).with_name('java') / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
            cp = str(classes) + os.pathsep + java_classpath(context.sim_repo)
            parity_cp = os.pathsep.join([str(context.engineering_dir / 'classes'), str(context.reference_indsvr_repo / 'target/test-classes'),
                str(context.reference_indsvr_repo / 'target/classes'), java_classpath(context.sim_repo)])
            require_hashes(used); require_hashes(original['source_sha256']); require_hashes(original['classes_sha256'])
            execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(classes)] + list(map(str, helpers)), output / 'helper-compile.log')
            proofs = {r['strategy']: r for r in read(context.engineering_dir / 'status.json')['records']}
            for row in original['queue']:
                resources = extra_slot_resources(output, args.minimum_free_memory_mib)
                while not resources['ready']:
                    write_status(output / 'status.json', dict(state='WAITING_FOR_EXTRA_SLOT_RESOURCES', completed=len(records),
                        total=100, resources=resources, production_write=False));time.sleep(10)
                    resources = extra_slot_resources(output, args.minimum_free_memory_mib)
                require_old_owner_stopped(handoff);require_hashes(used);require_hashes(original['source_sha256'])
                write_status(output / 'status.json', dict(state='RUNNING', completed=len(records), total=100,
                    current_strategy=row['strategy'], resources=resources, production_write=False))
                record = run_case(context, row, manifest_hash, ready, protocol, cp, parity_cp, proofs,
                    export_source=export_source, scope_fields=SCOPE_FIELDS)
                records.append(record);write_status(output / 'results.json', records)
                write_status(output / 'status.json', dict(state='RUNNING', updated_utc=datetime.now(timezone.utc).isoformat(),
                    completed=len(records), total=100, local_formal_qualified=sum(r['qualified'] for r in records),
                    published=0, production_write=False))
                print('DIRECTIONAL_CLOCK_PARALLEL_FORMAL', len(records), '/', 100, row['strategy'], record['reason'], flush=True)
            write_status(output / 'FORMAL_COMPLETE.json', dict(manifest_sha256=manifest_hash, completed=100,
                local_formal_qualified=sum(r['qualified'] for r in records), production_write=False))
        except Exception as error:
            write_status(output / 'FAILED.json', dict(completed=len(records), error=str(error), production_write=False));raise


if __name__ == '__main__': main()
