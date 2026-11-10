"""Replace the completed clock slot with100 frozen CUSUM scopes using the unchanged real finance path."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import time

import psutil

from recovery.export_cusum_drift_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.local_strategy_backtest import java_classpath
from recovery.run_directional_clock_batch import SCOPE_FIELDS, require_hashes
from recovery.run_directional_clock_parallel import extra_slot_resources, option
from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.run_ohlcv_profile_proxy_batch import run_case
from recovery.run_true_adx_batch import completed_case, read
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute
from recovery.watch_fixed_primary_supplements import parent_alive

PARENT_MODULE = 'recovery.run_directional_clock_parallel'
PARENT_SCHEMA = 'frozen_directional_clock_parallel_100_scopes_v1'


def frozen_queue(native, symbols):
    if len(symbols) != 10 or len(set(symbols)) != 10:
        raise ValueError('exactly ten distinct original symbols required')
    rows = []
    for symbol in sorted(symbols):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            for side in VARIANTS:
                _, item, descriptor = frozen_source(native, symbol, scene, side)
                rows.append(dict(descriptor, strategy=item['strategyName'], symbol=symbol, scene=scene))
    if len(rows) != 100 or len({r['strategy'] for r in rows}) != 100:
        raise ValueError('entire100-scope queue required, not100 independent mechanisms')
    return rows


def export_source(args, row):
    return export_candidate(args.indsvr_repo, args.output_dir / 'frozen', row['symbol'], row['scene'], row['side'])


def bind_parent(pid, created, folder, digest, previous=None):
    expected = dict(pid=pid, create_time=created, output_dir=str(folder), manifest_sha256=digest)
    if sha(folder / 'manifest.json') != digest or read(folder / 'manifest.json').get('schema') != PARENT_SCHEMA:
        raise ValueError('exact frozen directional-clock parent manifest required')
    if previous is not None:
        if any(previous.get(k) != v for k, v in expected.items()):
            raise ValueError('bound parent identity/plan changed')
        command = previous['command']
    else:
        process = psutil.Process(pid)
        if process.create_time() != created: raise ValueError('parent PID reused')
        command = process.cmdline()
    if (command.count('-m') != 1 or command[command.index('-m') + 1] != PARENT_MODULE
            or Path(option(command, 'output-dir')).resolve() != folder):
        raise ValueError('exact clock module and output required')
    return dict(expected, command=command)


def require_parent_complete(parent):
    folder = Path(parent['output_dir']); digest = parent['manifest_sha256']
    manifest, complete, status = read(folder / 'manifest.json'), read(folder / 'FORMAL_COMPLETE.json'), read(folder / 'status.json')
    queue = manifest.get('queue', [])
    if (sha(folder / 'manifest.json') != digest or manifest.get('schema') != PARENT_SCHEMA
            or complete.get('manifest_sha256') != digest or complete.get('completed') != 100
            or complete.get('production_write') is not False or status.get('completed') != 100
            or status.get('total') != 100 or len(queue) != 100 or len({r['strategy'] for r in queue}) != 100
            or (folder / 'FAILED.json').exists()):
        raise ValueError('clock must genuinely complete100, not disappear, fail or leave partial work')
    qualified, checkpoints = 0, {}
    for row in queue:
        case = folder / 'candidates' / row['strategy']; record = completed_case(case, digest)
        if any(record[k] != row[k] for k in SCOPE_FIELDS):
            raise ValueError('completed parent source scope changed')
        qualified += bool(record['qualified']); checkpoints[row['strategy']] = sha(case / 'checkpoint.json')
    if complete.get('local_formal_qualified') != qualified or status.get('local_formal_qualified') != qualified:
        raise ValueError('parent completed qualification count does not match immutable checkpoints')
    return dict(parent_manifest_sha256=digest, completed=100, qualified=qualified,
                checkpoint_sha256=checkpoints, financial_replay_performed=False, production_write=False)


def verify_context(args):
    java_dir = Path(__file__).with_name('java')
    fit = require_proof(args.fit_oracle_dir, java_dir, args.sim_repo)
    locked, locked_manifest = read(args.locked_oracle_dir / 'audit.json'), read(args.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != sha(args.locked_oracle_dir / 'manifest.json')
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('original twelve-case real locked replay proof required')
    engineering = read(args.engineering_dir / 'manifest.json'); complete = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json')
    if (sha(args.engineering_dir / 'manifest.json') != args.engineering_manifest_sha256
            or complete.get('manifest_sha256') != args.engineering_manifest_sha256 or complete.get('completed') != 2
            or complete.get('mathematics_tests') != 16 or complete.get('independent_suffix_fixtures') != 64
            or complete.get('regression_tests', 0) < 155 or complete.get('financial_validation_started') is not False
            or complete.get('production_write') is not False
            or complete['regression_manifest_sha256'] != sha(args.engineering_dir / 'regression-manifest.json')
            or complete['regression_log_sha256'] != sha(args.engineering_dir / 'full-research-regression.log')
            or engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_cusum_drift_candidate.py'))
            or engineering['wrapper_sha256'] != sha(Path(__file__).with_name('verify_cusum_drift.py'))
            or engineering['protocol_sha256'] != sha(args.protocol)
            or engineering['training_ready_sha256'] != sha(args.training_input_dir / 'READY.json')):
        raise ValueError('complete original16/64/two-source/155-regression frozen engineering proof required')
    native = source_file(args.indsvr_repo)
    sources = {str(native.with_name(n)): h for n, h in engineering['source_sha256'].items()}
    classes = {str(args.engineering_dir / 'classes' / n): h for n, h in complete['class_sha256'].items()}
    regression = read(args.engineering_dir / 'regression-manifest.json')
    for name, digest in regression['source_sha256'].items(): sources[str(native.with_name(name))] = digest
    reference_root = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    for name, digest in regression['reference_test_sha256'].items(): classes[str(reference_root / name)] = digest
    validator = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    classes[str(validator)] = engineering['source_validator_class_sha256']
    classes[str(reference_root / 'RepresentativeSignalParityCli.class')] = engineering['original_parity_cli_sha256']
    fit_manifest = read(args.fit_oracle_dir / 'manifest.json')
    for name, digest in fit_manifest['formal_class_sha256'].items():
        classes[str(args.sim_repo / 'target/classes/com/app/dc/service/simulation' / name)] = digest
    sources[str(args.sim_repo / 'config/application.properties')] = fit_manifest['execution_properties_sha256']
    require_hashes(sources); require_hashes(classes)
    ready, training, protocol = read(args.input_dir / 'READY.json'), read(args.training_input_dir / 'READY.json'), read(args.protocol)
    if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'cusum_drift_v1'
            or protocol.get('mechanism_group') != 'standardized_return_cusum_drift'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('original separated temporal/training periods and fixed-source policy required')
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(args.input_dir / (symbol + suffix)) != ready['files'][symbol][key]: raise ValueError('financial market bytes changed')
        if sha(args.training_input_dir / (symbol + '-15m.tsv')) != training['files'][symbol]['bars_sha256']:
            raise ValueError('training market bytes changed')
    # Freeze the entire new tools tree, not just a name-equivalent wrapper.
    tools = {str(p): sha(p) for p in Path(__file__).parent.glob('*.py')}
    helpers = [java_dir / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
    tools.update({str(p): sha(p) for p in helpers + [args.protocol]})
    evidence = {str(args.engineering_dir / n): sha(args.engineering_dir / n) for n in (
        'manifest.json', 'SOURCE_CONTRACT_COMPLETE.json', 'regression-manifest.json', 'full-research-regression.log')}
    tools.update(evidence)
    proof = dict(source_sha256=sources, classes_sha256=classes, tool_sha256=tools,
        ready_sha256=sha(args.input_dir / 'READY.json'), training_ready_sha256=sha(args.training_input_dir / 'READY.json'),
        engineering_manifest_sha256=args.engineering_manifest_sha256, fit_oracle_manifest_sha256=fit,
        locked_oracle_manifest_sha256=locked['manifest_sha256'])
    return proof, ready, protocol


def run_finance(args, manifest, digest, ready, protocol):
    proof = manifest['verification']; records = []; output = args.output_dir
    while not extra_slot_resources(output, 3072)['ready']:
        write_status(output / 'status.json', dict(state='WAITING_FOR_REPLACEMENT_SLOT_RESOURCES', completed=0, total=100,
            resources=extra_slot_resources(output, 3072), production_write=False)); time.sleep(10)
    require_hashes(proof['source_sha256']); require_hashes(proof['classes_sha256']); require_hashes(proof['tool_sha256'])
    classes = output / 'classes'; classes.mkdir(exist_ok=True)
    cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
    parity_cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
        str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    helpers = [Path(__file__).with_name('java') / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
    execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp, '-d', str(classes)] + list(map(str, helpers)), output / 'helper-compile.log')
    originals = {r['strategy']: r for r in read(args.engineering_dir / 'status.json')['records']}
    for row in manifest['queue']:
        resources = extra_slot_resources(output, 3072)
        while not resources['ready']:
            write_status(output / 'status.json', dict(state='WAITING_FOR_REPLACEMENT_SLOT_RESOURCES', completed=len(records),
                total=100, resources=resources, production_write=False)); time.sleep(10); resources = extra_slot_resources(output, 3072)
        require_hashes(proof['source_sha256']); require_hashes(proof['classes_sha256']); require_hashes(proof['tool_sha256'])
        write_status(output / 'status.json', dict(state='RUNNING', completed=len(records), total=100,
            current_strategy=row['strategy'], resources=resources, production_write=False))
        record = run_case(args, row, digest, ready, protocol, cp, parity_cp, originals,
                          export_source=export_source, scope_fields=SCOPE_FIELDS)
        records.append(record); write_status(output / 'results.json', records)
        write_status(output / 'status.json', dict(state='RUNNING', updated_utc=datetime.now(timezone.utc).isoformat(),
            completed=len(records), total=100, local_formal_qualified=sum(r['qualified'] for r in records),
            published=0, production_write=False))
        print('CUSUM_DRIFT_FORMAL', len(records), '/', 100, row['strategy'], record['reason'], flush=True)
    write_status(output / 'FORMAL_COMPLETE.json', dict(manifest_sha256=digest, completed=100,
        local_formal_qualified=sum(r['qualified'] for r in records), production_write=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir', 'protocol',
             'engineering-dir', 'fit-oracle-dir', 'locked-oracle-dir', 'output-dir', 'wait-for-parent-dir')
    for name in names: parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--engineering-manifest-sha256', required=True)
    parser.add_argument('--wait-for-parent-pid', type=int, required=True)
    parser.add_argument('--wait-for-parent-create-time', type=float, required=True)
    parser.add_argument('--wait-for-parent-manifest-sha256', required=True)
    args = parser.parse_args()
    for name in names:
        key = name.replace('-', '_'); setattr(args, key, getattr(args, key).resolve())
    verification, ready, protocol = verify_context(args)
    queue = frozen_queue(source_file(args.indsvr_repo).read_text(encoding='utf-8'), ready['symbols'])
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(output):
        if (output / 'FAILED.json').exists() or (output / 'FORMAL_COMPLETE.json').exists():
            raise ValueError('preserve terminal attempt; inspect it instead of blind replay')
        previous = read(output / 'manifest.json') if (output / 'manifest.json').exists() else None
        parent = bind_parent(args.wait_for_parent_pid, args.wait_for_parent_create_time, args.wait_for_parent_dir,
            args.wait_for_parent_manifest_sha256, previous.get('parent_identity') if previous else None)
        manifest = dict(schema='frozen_cusum_drift_100_scopes_v1', queue=queue, parent_identity=parent, verification=verification,
            mechanism_group='standardized_return_cusum_drift', replacement_serial_slots=1, added_financial_slots=0,
            minimum_available_memory_mib=3072, server_codegen_allowed=False, production_write=False)
        if previous is not None and previous != manifest: raise ValueError('frozen CUSUM source/engine/queue changed')
        if previous is None: write_status(output / 'manifest.json', manifest)
        digest = sha(output / 'manifest.json')
        try:
            while parent_alive(parent):
                if (Path(parent['output_dir']) / 'FAILED.json').exists(): raise ValueError('bound clock parent failed; preserve both attempts')
                write_status(output / 'status.json', dict(state='WAITING_FOR_BOUND_CLOCK_BATCH', completed=0, total=100,
                    parent_pid=parent['pid'], financial_dispatch_started=False, production_write=False)); time.sleep(10)
            audit = require_parent_complete(parent); write_status(output / 'PARENT_COMPLETION_AUDIT.json', audit)
            after_wait, ready, protocol = verify_context(args)
            if after_wait != verification: raise ValueError('frozen inputs/tools/classes changed during wait')
            run_finance(args, manifest, digest, ready, protocol)
        except Exception as error:
            write_status(output / 'FAILED.json', dict(error=str(error), production_write=False)); raise


if __name__ == '__main__': main()
