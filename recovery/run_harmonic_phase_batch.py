"""Fixed harmonic-phase -> original primary/strict/disjoint holdout; replaces a genuinely completed signed-runs slot only."""
import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import time

import psutil

from recovery.export_harmonic_phase_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.local_strategy_backtest import java_classpath
from recovery.run_directional_clock_batch import SCOPE_FIELDS, require_hashes
from recovery.run_directional_clock_parallel import extra_slot_resources, option
from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.run_ohlcv_profile_proxy_batch import run_case
from recovery.run_true_adx_batch import completed_case, read
from recovery.verify_cusum_identity_matrix import parse_parity
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute
from recovery.watch_fixed_primary_supplements import parent_alive

PARENT_MODULE = 'recovery.run_runs_clustering_batch'
PARENT_SCHEMA = 'frozen_runs_clustering_100_scopes_v1'


def frozen_queue(native, symbols):
    if len(symbols) != 10 or len(set(symbols)) != 10:
        raise ValueError('ten distinct original symbols required')
    rows = []
    for symbol in sorted(symbols):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            for side in VARIANTS:
                _, item, descriptor = frozen_source(native, symbol, scene, side)
                rows.append(dict(descriptor, strategy=item['strategyName'], symbol=symbol, scene=scene))
    if len(rows) != 100 or len({r['strategy'] for r in rows}) != 100:
        raise ValueError('entire100 scopes required, not100 independent mechanisms')
    return rows


def export_source(args, row):
    return export_candidate(args.indsvr_repo, args.output_dir / 'frozen', row['symbol'], row['scene'], row['side'])


def bind_parent(pid, created, folder, digest, previous=None):
    expected = dict(pid=pid, create_time=created, output_dir=str(folder), manifest_sha256=digest)
    if sha(folder / 'manifest.json') != digest or read(folder / 'manifest.json').get('schema') != PARENT_SCHEMA:
        raise ValueError('exact frozen signed-runs parent manifest required')
    if previous is not None:
        if any(previous.get(k) != v for k, v in expected.items()): raise ValueError('bound parent identity/plan changed')
        command = previous['command']
    else:
        process = psutil.Process(pid)
        if process.create_time() != created: raise ValueError('parent PID reused')
        command = process.cmdline()
    if (command.count('-m') != 1 or command[command.index('-m') + 1] != PARENT_MODULE
            or Path(option(command, 'output-dir')).resolve() != folder):
        raise ValueError('exact signed-runs module and output required')
    return dict(expected, command=command)


def require_parent_complete(parent):
    root = Path(parent['output_dir']); digest = parent['manifest_sha256']
    manifest, marker, status = read(root / 'manifest.json'), read(root / 'FORMAL_COMPLETE.json'), read(root / 'status.json')
    queue = manifest.get('queue', [])
    if (sha(root / 'manifest.json') != digest or manifest.get('schema') != PARENT_SCHEMA
            or marker.get('manifest_sha256') != digest or marker.get('completed') != 100
            or marker.get('production_write') is not False or status.get('completed') != 100
            or status.get('total') != 100 or len(queue) != 100 or len({r['strategy'] for r in queue}) != 100
            or (root / 'FAILED.json').exists()):
        raise ValueError('signed-runs must genuinely complete100; disappearance or failure is not completion')
    qualified, checkpoints = 0, {}
    for row in queue:
        case = root / 'candidates' / row['strategy']; saved = completed_case(case, digest)
        if any(saved[k] != row[k] for k in SCOPE_FIELDS): raise ValueError('completed parent source scope changed')
        qualified += bool(saved['qualified']); checkpoints[row['strategy']] = sha(case / 'checkpoint.json')
    if marker.get('local_formal_qualified') != qualified or status.get('local_formal_qualified') != qualified:
        raise ValueError('parent qualification count does not match immutable checkpoints')
    return dict(parent_manifest_sha256=digest, completed=100, qualified=qualified,
        checkpoint_sha256=checkpoints, financial_replay_performed=False, production_write=False)


def engineering_evidence(args):
    root = args.engineering_dir
    if (root / 'FAILED.json').exists() or not (root / 'SOURCE_CONTRACT_COMPLETE.json').is_file():
        raise ValueError('complete successful harmonic-phase engineering required before any formal runner starts')
    manifest, marker = read(root / 'manifest.json'), read(root / 'SOURCE_CONTRACT_COMPLETE.json')
    status = read(root / 'status.json')
    if (sha(root / 'manifest.json') != args.engineering_manifest_sha256
            or manifest.get('schema') != 'harmonic_phase_engineering_v1'
            or marker.get('manifest_sha256') != args.engineering_manifest_sha256 or marker.get('completed') != 2
            or marker.get('mathematics_tests') != 16 or marker.get('independent_raw_ohlc_fixtures') != 64
            or marker.get('independent_complex_and_convolution_oracles') is not True or marker.get('regression_tests', 0) < 188
            or marker.get('financial_validation_started') is not False or marker.get('production_write') is not False
            or status.get('state') != 'COMPLETE' or status.get('completed') != 2 or status.get('total') != 2
            or manifest.get('mechanism_group') != 'causal_harmonic_phase_projection'
            or manifest.get('financial_validation_started') is not False or manifest.get('forward_pnl_read') is not False
            or manifest.get('production_write') is not False
            or manifest['protocol_sha256'] != sha(args.protocol)
            or manifest['training_ready_sha256'] != sha(args.training_input_dir / 'READY.json')
            or manifest['exporter_sha256'] != sha(Path(__file__).with_name('export_harmonic_phase_candidate.py'))
            or manifest['wrapper_sha256'] != sha(Path(__file__).with_name('verify_harmonic_phase.py'))
            or marker['regression_manifest_sha256'] != sha(root / 'regression-manifest.json')
            or marker['regression_log_sha256'] != sha(root / 'full-research-regression.log')):
        raise ValueError('genuine16/64/two-source/188-regression harmonic-phase proof required')
    require_hashes(manifest['critical_sha256'])
    class_map = {str(root / 'classes' / n): h for n, h in marker['class_sha256'].items()}
    if not class_map or set(class_map) != {str(p) for p in (root / 'classes').rglob('*.class')}:
        raise ValueError('complete frozen engineering class membership required')
    require_hashes(class_map)
    native = source_file(args.indsvr_repo)
    sources = {str(native.with_name(n)): h for n, h in manifest['source_sha256'].items()}
    regression = read(root / 'regression-manifest.json')
    if regression.get('engineering_manifest_sha256') != args.engineering_manifest_sha256:
        raise ValueError('regression is not bound to the original engineering')
    sources.update({str(native.with_name(n)): h for n, h in regression['source_sha256'].items()})
    require_hashes(sources)
    evidence = {str(root / n): sha(root / n) for n in ('manifest.json', 'SOURCE_CONTRACT_COMPLETE.json',
        'regression-manifest.json', 'full-research-regression.log', 'compile.log', 'mathematics-tests.log', 'regression-compile.log')}
    if 'OK (16 tests)' not in (root / 'mathematics-tests.log').read_text(encoding='utf-8'):
        raise ValueError('actual16 mathematics result required')
    regression_text = (root / 'full-research-regression.log').read_text(encoding='utf-8')
    if 'FAILURES' in regression_text or ('OK (' + str(marker['regression_tests']) + ' tests)') not in regression_text:
        raise ValueError('actual complete regression result required')
    records = marker.get('records', [])
    if len(records) != 2 or {r['side'] for r in records} != {1, -1}:
        raise ValueError('both actual generated source directions required')
    for record in records:
        source, item, descriptor = frozen_source(native.read_text(encoding='utf-8'), 'BTCUSDT', 'trend', record['side'])
        name = item['strategyName']; frozen = root / 'frozen' / name
        source_path, seed = frozen / 'GeneratedStrategy.java', frozen / 'seed.json'
        parity, validator = root / 'logs' / (name + '-parity.log'), root / 'logs' / (name + '-source.log')
        if (record['strategy'] != name or any(record[k] != descriptor[k] for k in descriptor)
                or type(record['side']) is not int or record.get('bars') != 35040 or record.get('mismatches') != 0
                or record.get('signals', 0) <= 0 or record['source_sha256'] != sha(source_path)
                or record['source_sha256'] != hashlib.sha256(source.encode()).hexdigest()
                or record['artifact_sha256'] != sha(Path(record['artifact_path']))
                or read(seed) != {'strategies': [item]} or not validator.is_file()
                or parse_parity(parity.read_text(encoding='utf-8')) != record['signals']):
            raise ValueError('actual full-year source/JAR/seed/log evidence changed')
        for path in (source_path, seed, Path(record['artifact_path']), parity, validator): evidence[str(path)] = sha(path)
    return manifest, marker, sources, class_map, evidence


def verify_context(args):
    engineering, complete, sources, classes, evidence = engineering_evidence(args)
    java_dir = Path(__file__).with_name('java')
    fit = require_proof(args.fit_oracle_dir, java_dir, args.sim_repo)
    locked, locked_manifest = read(args.locked_oracle_dir / 'audit.json'), read(args.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != sha(args.locked_oracle_dir / 'manifest.json')
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('original twelve-case locked real replay proof required')
    fit_manifest = read(args.fit_oracle_dir / 'manifest.json')
    for name, digest in fit_manifest['formal_class_sha256'].items():
        classes[str(args.sim_repo / 'target/classes/com/app/dc/service/simulation' / name)] = digest
    sources[str(args.sim_repo / 'config/application.properties')] = fit_manifest['execution_properties_sha256']
    ready, training, protocol = read(args.input_dir / 'READY.json'), read(args.training_input_dir / 'READY.json'), read(args.protocol)
    if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'harmonic_phase_v1'
            or protocol.get('mechanism_group') != 'causal_harmonic_phase_projection'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'
            or protocol.get('minimum_forward_contribution') != '0.20'
            or ready.get('begin') != protocol['primary_begin']
            or ready.get('primary_end_inclusive') != protocol['primary_end_inclusive']
            or ready.get('holdout_begin') != protocol['holdout_begin'] or ready.get('end') != protocol['holdout_end_inclusive']
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('unchanged separated temporal/training windows and fixed harmonic-phase policy required')
    data = {}
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            data[str(args.input_dir / (symbol + suffix))] = ready['files'][symbol][key]
        data[str(args.training_input_dir / (symbol + '-15m.tsv'))] = training['files'][symbol]['bars_sha256']
    tools = {str(p): sha(p) for p in Path(__file__).parent.glob('*.py')}
    helpers = [java_dir / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
    tools.update({str(p): sha(p) for p in helpers + [args.protocol, args.input_dir / 'READY.json', args.training_input_dir / 'READY.json']})
    tools.update(evidence); tools.update(engineering['critical_sha256'])
    if args.parent_binding is not None:
        if sha(args.parent_binding) != args.parent_binding_sha256: raise ValueError('recorded live parent binding changed')
        tools[str(args.parent_binding)] = args.parent_binding_sha256
    runtime_roots = [args.engineering_dir / 'classes'] + [repo / 'target' / suffix
        for repo in (args.reference_indsvr_repo, args.sim_repo) for suffix in ('test-classes', 'classes')]
    runtime_classes = dict(engineering['reference_class_sha256']); runtime_classes.update(classes)
    proof = dict(source_sha256=sources, classes_sha256=classes, tool_sha256=tools, data_sha256=data,
        runtime_jar_sha256=engineering['runtime_jar_sha256'],
        runtime_jar_roots=[str(args.sim_repo / 'target' / n) for n in ('dependency', 'javalib')],
        runtime_class_sha256=runtime_classes,
        runtime_class_roots=[str(p) for p in runtime_roots], java_executables=engineering['java_executables'],
        java_option_environment_sha256=engineering['java_option_environment_sha256'],
        engineering_manifest_sha256=args.engineering_manifest_sha256, fit_oracle_manifest_sha256=fit,
        locked_oracle_manifest_sha256=locked['manifest_sha256'], original_records=complete['records'])
    check_snapshot(proof); return proof, ready, protocol


def check_snapshot(proof, row=None):
    for key in ('source_sha256', 'classes_sha256', 'tool_sha256', 'runtime_jar_sha256'):
        require_hashes(proof[key])
    current_classes = {str(p) for root in proof['runtime_class_roots'] for p in Path(root).rglob('*.class')}
    jars = proof['runtime_jar_sha256']
    current_jars = {str(p) for root in proof['runtime_jar_roots'] for p in Path(root).glob('*.jar')}
    executables = {name: str(Path(shutil.which(name)).resolve()) for name in proof['java_executables']}
    options = {name: hashlib.sha256(os.environ.get(name, '').encode()).hexdigest()
        for name in proof['java_option_environment_sha256']}
    if (current_classes != set(proof['runtime_class_sha256']) or current_jars != set(jars)
            or executables != proof['java_executables'] or options != proof['java_option_environment_sha256']):
        raise ValueError('frozen runtime membership/Java selection/options changed')
    scoped = {p: h for p, h in proof['data_sha256'].items()
        if row is None or Path(p).name.startswith(row['symbol'] + '-')}
    require_hashes(scoped)


def run_finance(args, manifest, digest, ready, protocol):
    proof = manifest['verification']; records = []; output = args.output_dir
    def guard():
        resources = extra_slot_resources(output, 3072)
        while not resources['ready']:
            write_status(output / 'status.json', dict(state='WAITING_FOR_REPLACEMENT_SLOT_RESOURCES',
                completed=len(records), total=100, resources=resources, production_write=False))
            time.sleep(10); resources = extra_slot_resources(output, 3072)
    guard(); check_snapshot(proof)
    classes = output / 'classes'; classes.mkdir(exist_ok=True)
    cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
    parity_cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
        str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    helpers = [Path(__file__).with_name('java') / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
    execute(['javac', '-J-Xmx512m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp, '-d', str(classes)]
        + list(map(str, helpers)), output / 'helper-compile.log')
    originals = {r['strategy']: r for r in proof['original_records']}
    for row in manifest['queue']:
        guard(); check_snapshot(proof, row)
        write_status(output / 'status.json', dict(state='RUNNING', completed=len(records), total=100,
            current_strategy=row['strategy'], production_write=False))
        record = run_case(args, row, digest, ready, protocol, cp, parity_cp, originals,
            export_source=export_source, scope_fields=SCOPE_FIELDS)
        records.append(record); write_status(output / 'results.json', records)
        write_status(output / 'status.json', dict(state='RUNNING', updated_utc=datetime.now(timezone.utc).isoformat(),
            completed=len(records), total=100, local_formal_qualified=sum(r['qualified'] for r in records), published=0, production_write=False))
        print('HARMONIC_PHASE_FORMAL', len(records), '/', 100, row['strategy'], record['reason'], flush=True)
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
    parser.add_argument('--parent-binding', type=Path)
    parser.add_argument('--parent-binding-sha256')
    args = parser.parse_args()
    for name in names + (('parent-binding',) if args.parent_binding is not None else ()):
        key = name.replace('-', '_'); setattr(args, key, getattr(args, key).resolve())
    if bool(args.parent_binding) != bool(args.parent_binding_sha256): raise ValueError('both saved parent binding and digest required')
    verification, ready, protocol = verify_context(args)
    queue = frozen_queue(source_file(args.indsvr_repo).read_text(encoding='utf-8'), ready['symbols'])
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(output):
        if (output / 'FAILED.json').exists() or (output / 'FORMAL_COMPLETE.json').exists():
            raise ValueError('preserve terminal attempt, never blind replay')
        previous = read(output / 'manifest.json') if (output / 'manifest.json').exists() else None
        saved = previous['parent_identity'] if previous else read(args.parent_binding)['parent_identity'] if args.parent_binding else None
        parent = bind_parent(args.wait_for_parent_pid, args.wait_for_parent_create_time, args.wait_for_parent_dir,
            args.wait_for_parent_manifest_sha256, saved)
        manifest = dict(schema='frozen_harmonic_phase_100_scopes_v1', queue=queue, parent_identity=parent, verification=verification,
            mechanism_group='causal_harmonic_phase_projection', replacement_serial_slots=1, added_financial_slots=0,
            minimum_available_memory_mib=3072, server_codegen_allowed=False, production_write=False)
        if previous is not None and previous != manifest: raise ValueError('frozen harmonic-phase source/engine/queue changed')
        if previous is None: write_status(output / 'manifest.json', manifest)
        digest = sha(output / 'manifest.json')
        try:
            while parent_alive(parent):
                if (Path(parent['output_dir']) / 'FAILED.json').exists(): raise ValueError('bound signed-runs parent failed; preserve both attempts')
                write_status(output / 'status.json', dict(state='WAITING_FOR_BOUND_RUNS_BATCH', completed=0, total=100,
                    parent_pid=parent['pid'], financial_dispatch_started=False, production_write=False)); time.sleep(10)
            write_status(output / 'PARENT_COMPLETION_AUDIT.json', require_parent_complete(parent))
            after_wait, ready, protocol = verify_context(args)
            if after_wait != verification: raise ValueError('frozen inputs/tools/classes changed during wait')
            run_finance(args, manifest, digest, ready, protocol)
        except Exception as error:
            write_status(output / 'FAILED.json', dict(error=str(error), production_write=False)); raise


if __name__ == '__main__': main()
