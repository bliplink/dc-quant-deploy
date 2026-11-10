"""Training-only pilot: exact source/full-class identity equivalence AND an actual original full-year replay; never enables reuse."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import time
import zipfile

from recovery.class_identity_equivalence import require_jar_identity_equivalence, require_source_identity_equivalence
from recovery.export_cusum_drift_candidate import export_candidate, source_file
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.run_directional_clock_batch import require_hashes
from recovery.run_directional_clock_parallel import extra_slot_resources
from recovery.run_fit_risk_catalog_batch import write_status
from recovery.run_true_adx_batch import read
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute


def wait_resources(output):
    resources = extra_slot_resources(output, 3072)
    while not resources['ready']:
        write_status(output / 'status.json', dict(state='WAITING_FOR_TRAINING_PILOT_RESOURCES', resources=resources,
            financial_validation_started=False, production_write=False))
        time.sleep(10); resources = extra_slot_resources(output, 3072)


def adapter_bindings(args):
    relative = 'com/app/dc/signal/LegacyLiveSignalAdapter.class'
    roots = [args.engineering_dir / 'classes', args.reference_indsvr_repo / 'target/test-classes',
             args.reference_indsvr_repo / 'target/classes', args.sim_repo / 'target/test-classes', args.sim_repo / 'target/classes']
    bindings = []
    for root in roots:
        if (root / relative).exists(): bindings.append(dict(path=str(root / relative), class_sha256=sha(root / relative)))
    for folder in ('dependency', 'javalib'):
        for jar in sorted((args.sim_repo / 'target' / folder).glob('*.jar')):
            with zipfile.ZipFile(jar) as archive:
                if relative in archive.namelist():
                    bindings.append(dict(path=str(jar), artifact_sha256=sha(jar),
                        class_sha256=hashlib.sha256(archive.read(relative)).hexdigest()))
    if not bindings or len({r['class_sha256'] for r in bindings}) != 1:
        raise ValueError('actual adapter classpath copies missing or byte-divergent; no assumption about class loading')
    return bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'engineering-dir', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--side', type=int, choices=(1, -1), default=1)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path): setattr(args, name, value.resolve())
    output = args.output_dir
    if output.exists(): raise ValueError('fresh pilot directory required; preserve every old attempt')
    complete = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json'); engineering = read(args.engineering_dir / 'manifest.json')
    if (complete.get('completed') != 2 or complete.get('mathematics_tests') != 16
            or complete.get('independent_suffix_fixtures') != 64 or complete.get('regression_tests') != 155
            or complete.get('manifest_sha256') != sha(args.engineering_dir / 'manifest.json')
            or sha(args.engineering_dir / 'manifest.json') != '1aee7da502d093ab773a0c6b48ace9d127969b7c0a631219dcddb5a8ecfafb2b'
            or complete.get('financial_validation_started') is not False
            or engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_cusum_drift_candidate.py'))):
        raise ValueError('exact original CUSUM source/validator/full-year/155-regression proof required')
    native = source_file(args.indsvr_repo)
    require_hashes({str(native.with_name(n)): h for n, h in engineering['source_sha256'].items()})
    require_hashes({str(args.engineering_dir / 'classes' / n): h for n, h in complete['class_sha256'].items()})
    reference_root = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    validator = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    if sha(reference_root / 'RepresentativeSignalParityCli.class') != engineering['original_parity_cli_sha256'] or sha(validator) != engineering['source_validator_class_sha256']:
        raise ValueError('original real validator/parity CLI changed')
    ready = read(args.training_input_dir / 'READY.json'); bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(args.training_input_dir / 'READY.json') != engineering['training_ready_sha256']
            or sha(bars) != ready['files']['BTCUSDT']['bars_sha256']):
        raise ValueError('unchanged original training-only year required')
    original = next(r for r in read(args.engineering_dir / 'status.json')['records'] if r['side'] == args.side)
    canonical_source = args.engineering_dir / 'frozen' / original['strategy'] / 'GeneratedStrategy.java'
    canonical_jar = Path(original['artifact_path'])
    if sha(canonical_source) != original['source_sha256'] or sha(canonical_jar) != original['artifact_sha256']:
        raise ValueError('original actual source/JAR changed')
    environment = adapter_bindings(args)
    frozen_paths = {str(native.with_name(n)): h for n, h in engineering['source_sha256'].items()}
    frozen_paths.update({str(args.engineering_dir / 'classes' / n): h for n, h in complete['class_sha256'].items()})
    frozen_paths.update({str(p): sha(p) for p in (canonical_source, canonical_jar, bars,
        reference_root / 'RepresentativeSignalParityCli.class', validator, Path(__file__),
        Path(__file__).with_name('class_identity_equivalence.py'), Path(__file__).with_name('export_cusum_drift_candidate.py'),
        Path(__file__).with_name('local_strategy_backtest.py'))})
    output.mkdir(parents=True)
    write_status(output / 'manifest.json', dict(schema='cusum_identity_training_pilot_v1', side=args.side,
        engineering_manifest_sha256=sha(args.engineering_dir / 'manifest.json'),
        canonical_source_sha256=original['source_sha256'], canonical_artifact_sha256=original['artifact_sha256'],
        training_bars_sha256=sha(bars), adapter_bindings=environment,
        frozen_input_and_tool_sha256=frozen_paths,
        tool_sha256={str(p): sha(p) for p in (Path(__file__), Path(__file__).with_name('class_identity_equivalence.py'))},
        runtime_reuse_enabled=False, financial_validation_started=False, new_holdout_read=False, production_write=False))
    try:
        wait_resources(output); require_hashes(frozen_paths)
        write_status(output / 'status.json', dict(state='COMPILING_AND_COMPARING_IDENTITY', financial_validation_started=False, production_write=False))
        frozen, item, descriptor = export_candidate(args.indsvr_repo, output / 'frozen', 'BTCUSDT', 'range', args.side)
        source_path = frozen / 'GeneratedStrategy.java'; source = source_path.read_text(encoding='utf-8')
        require_source_identity_equivalence(canonical_source.read_text(encoding='utf-8'), original['strategy'], source, item['strategyName'])
        artifact, entry, _ = compile_source(source, args.sim_repo, output / 'artifacts' / item['strategyName'])
        start = time.monotonic()
        identity = require_jar_identity_equivalence(canonical_jar, original['strategy'], artifact, item['strategyName'])
        equivalence_seconds = time.monotonic() - start
        cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
            str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
        execute(['javap', '-p', '-c', '-cp', cp, 'com.app.dc.signal.LegacyLiveSignalAdapter'], output / 'actual-adapter-javap.log')
        execute(['java', '-Xmx256m', '-cp', cp, 'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
            '--validate-source', str(source_path), item['request']['logicSummary'], item['strategyName']], output / 'real-source-validator.log')
        wait_resources(output); require_hashes(frozen_paths)
        write_status(output / 'status.json', dict(state='RUNNING_ORIGINAL_FULL_YEAR_PARITY', financial_validation_started=False, production_write=False))
        start = time.monotonic()
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', str(bars), 'BTCUSDT', '2023-01-01', '2023-12-31',
            descriptor['hypothesis'], str(artifact), entry], output / 'actual-original-full-year-parity.log')
        replay_seconds = time.monotonic() - start
        found = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
        if not found or int(found[1]) != 35040 or int(found[2]) != original['signals'] or found[2] != found[3] or int(found[4]) != 0:
            raise ValueError('actual original full-year signal/risk parity must independently confirm identity pilot')
        controls = []
        for label, before, after in (
                ('entry_constant', 'DRIFT_ALLOWANCE = 0.25;', 'DRIFT_ALLOWANCE = 0.26;'),
                ('exit_stop', 'side * 1.5 * risk', 'side * 1.6 * risk')):
            if source.count(before) != 1: raise ValueError('exact diagnostic negative-control edit required')
            changed = source.replace(before, after, 1)
            try:
                require_source_identity_equivalence(canonical_source.read_text(encoding='utf-8'), original['strategy'], changed, item['strategyName'])
                raise AssertionError('changed arithmetic escaped source rejection')
            except ValueError: pass
            wait_resources(output); require_hashes(frozen_paths)
            write_status(output / 'status.json', dict(state='RUNNING_NEGATIVE_CONTROLS', label=label,
                financial_validation_started=False, production_write=False))
            control_jar, _, control_source = compile_source(changed, args.sim_repo, output / 'negative-controls' / label)
            try:
                require_jar_identity_equivalence(canonical_jar, original['strategy'], control_jar, item['strategyName'])
                raise AssertionError('changed arithmetic escaped full class-file rejection')
            except ValueError: pass
            controls.append(dict(label=label, source_sha256=sha(control_source), artifact_sha256=sha(control_jar),
                source_rejected=True, bytecode_rejected=True, financial_replay_started=False))
        audit = dict(schema='cusum_identity_training_pilot_observation_v1', manifest_sha256=sha(output / 'manifest.json'),
            canonical_strategy=original['strategy'], canonical_source_sha256=original['source_sha256'],
            candidate_strategy=item['strategyName'], source_sha256=sha(source_path), artifact_sha256=sha(artifact),
            identity_proof=identity, training_bars=35040, signals=int(found[2]), mismatches=0,
            identity_comparison_seconds=equivalence_seconds, full_year_parity_seconds=replay_seconds,
            negative_controls=controls, adapter_javap_sha256=sha(output / 'actual-adapter-javap.log'),
            full_year_log_sha256=sha(output / 'actual-original-full-year-parity.log'),
            runtime_reuse_enabled=False, all_scopes_reuse_ready=False, financial_validation_started=False,
            old_financial_results_replayed=False, new_holdout_read=False, production_write=False)
        write_status(output / 'audit.json', audit)
        write_status(output / 'PILOT_COMPLETE.json', dict(manifest_sha256=sha(output / 'manifest.json'), audit_sha256=sha(output / 'audit.json'),
            training_only=True, runtime_reuse_enabled=False, production_write=False))
        write_status(output / 'status.json', dict(state='COMPLETE', runtime_reuse_enabled=False,
            financial_validation_started=False, production_write=False))
        print('CUSUM_IDENTITY_TRAINING_PILOT_COMPLETE', 'classes', len(identity['normalized_class_sha256']),
            'signals', found[2], 'mismatches', found[4], 'runtime_reuse_enabled', False, flush=True)
    except Exception as error:
        write_status(output / 'FAILED.json', dict(error=str(error), financial_validation_started=False, production_write=False)); raise


if __name__ == '__main__': main()
