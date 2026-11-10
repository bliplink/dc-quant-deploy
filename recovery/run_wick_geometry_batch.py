"""Fixed repaired-wick sources through unchanged v4 and disjoint holdout; no publication."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import time

from recovery.export_wick_geometry_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.local_strategy_backtest import build_parameters, compile_source, java_classpath
from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_catalog_batch import exclusive_batch, resource_state, write_status
from recovery.run_true_adx_batch import completed_case, read
from recovery.temporal_admission_contract import require_temporally_isolated_admission
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_wick_geometry_repair import execute


def frozen_queue(native, symbols):
    if len(symbols) != 10 or len(set(symbols)) != 10:
        raise ValueError('exactly ten distinct frozen symbols required')
    result = []
    for symbol in sorted(symbols):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            for side in VARIANTS:
                _, item, descriptor = frozen_source(native, symbol, scene, side)
                result.append(dict(descriptor, strategy=item['strategyName'], symbol=symbol, scene=scene))
    if len(result) != 100 or len({row['strategy'] for row in result}) != 100:
        raise ValueError('100 unique scopes, not independent mechanisms, required')
    return result


def run_case(args, row, manifest_hash, ready, protocol, cp, parity_cp, proof_records):
    output = args.output_dir / 'candidates' / row['strategy']
    if (output / 'checkpoint.json').exists():
        saved = completed_case(output, manifest_hash)
        if any(saved[key] != row[key] for key in ('strategy', 'symbol', 'scene', 'hypothesis', 'family', 'mechanism_group')):
            raise ValueError('completed wick scope/mechanism changed')
        return saved
    if output.exists():
        raise ValueError('partial attempt: diagnose without replay: ' + str(output))
    output.mkdir(parents=True)
    frozen, item, _ = export_candidate(args.indsvr_repo, args.output_dir / 'frozen', row['symbol'], row['scene'], row['side'])
    source = frozen / 'GeneratedStrategy.java'
    original = proof_records.get(row['strategy']) if row['symbol'] == 'BTCUSDT' and row['scene'] == 'trend' else None
    if original:
        artifact, entry = Path(original['artifact_path']), original['entry_class']
        if original['source_sha256'] != sha(source) or original['artifact_sha256'] != sha(artifact):
            raise ValueError('canonical repaired source/artifact changed')
        signals = original['signals']
    else:
        artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifact')
        execute(['java', '-Xmx256m', '-cp', parity_cp,
            'com.app.dc.service.strategy.research.WickGeometryRepairSignalParityCli', '--validate-source', str(source),
            item['request']['logicSummary'], row['strategy']], output / 'source-validator.log')
        text = execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', parity_cp,
            'com.app.dc.service.strategy.research.WickGeometryRepairSignalParityCli',
            str(args.training_input_dir / (row['symbol'] + '-15m.tsv')), row['symbol'], '2023-01-01', '2023-12-31',
            str(artifact), entry, row['strategy'], str(row['side'])], output / 'training-signal-parity.log')
        match = re.search(r'WICK_GEOMETRY_PARITY bars=(\d+) expectedSignals=(\d+) exportedSignals=(\d+) legacySignals=(\d+) mismatches=(\d+)', text)
        if not match or int(match[1]) != 35040 or match[2] != match[3] or int(match[5]) != 0:
            raise ValueError('scoped independent geometry/compiled source parity failed')
        signals = int(match[2])
    source_hash = sha(source)
    write_status(output / 'source-contract.json', {'source_path': str(source), 'source_sha256': source_hash,
        'artifact_path': str(artifact), 'artifact_sha256': sha(artifact), 'seed_sha256': sha(frozen / 'seed.json'),
        'training_bars': 35040, 'training_signals': signals, 'nonzero_training_signal_coverage': signals > 0,
        'mismatches': 0, 'canonical_proof_reused': original is not None, 'production_write': False})
    files = ready['files'][row['symbol']]
    spec = {'schema': 'offline_temporal_replay_v1', 'researchMode': 'fixed_full_primary',
        'strategyName': row['strategy'], 'strategyVersion': 'v1', 'symbol': row['symbol'], 'scene': row['scene'],
        'beginDate': protocol['primary_begin'], 'endDate': protocol['primary_end_inclusive'], 'formalHoldout': False,
        'protocolPath': str(args.protocol), 'protocolSha256': sha(args.protocol), 'lockedParameters': {},
        'sourcePath': str(source), 'sourceSha256': source_hash, 'artifactPath': str(artifact),
        'artifactSha256': sha(artifact), 'entryClass': entry, 'candidateParameters': build_parameters(item['request']),
        'barsPath': str(args.input_dir / (row['symbol'] + '-15m.tsv')), 'barsSha256': files['bars_sha256'],
        'scenesPath': str(args.input_dir / (row['symbol'] + '-scenes.tsv')), 'scenesSha256': files['scenes_sha256']}

    def replay(label, classname, specification):
        write_status(output / (label + '-spec.json'), specification)
        write_status(output / (label.upper() + '_STARTED.json'), {'manifest_sha256': manifest_hash,
            'source_sha256': source_hash, 'never_repeat_as_parameter_search': True})
        execute(['java', '-Xmx768m', '-Duser.timezone=UTC', '-cp', cp,
            'com.app.dc.service.simulation.' + classname, str(output / (label + '-spec.json')),
            str(args.sim_repo / 'config/application.properties'), str(output / (label + '.json'))], output / (label + '.log'))
        return read(output / (label + '.json'))

    primary = replay('primary', 'FixedSourcePrimaryReplayCli', spec)
    qualified, reason, result_path = False, primary['qualificationReason'], None
    if primary['primaryQualified']:
        if primary['selectedParameters'] != {} or primary['parameterGridSearch'] is not False:
            raise ValueError('fixed representative parameters changed')
        holdout = replay('holdout', 'OfflineTemporalReplayCli', dict(spec, researchMode='frozen_holdout',
            beginDate=protocol['holdout_begin'], endDate=protocol['holdout_end_inclusive'],
            primaryEndDate=protocol['primary_end_inclusive'], formalHoldout=True))
        qualified = holdout['passed']
        reason = 'qualified' if qualified else 'separate_chronological_holdout_failed'
        result = dict(primary['result'], admissionSchema='local_temporal_holdout_v2', beginDate=spec['beginDate'],
            endDate=spec['endDate'], selectedParameters={}, holdout=holdout, qualified=qualified,
            qualificationReason=reason, marketDataSource='local_ready_tsv')
        admission = {'mode': 'LOCAL_CODEX_TEMPORAL_PRE_ADMISSION', 'strategyName': row['strategy'], 'symbol': row['symbol'],
            'scene': row['scene'], 'sourceFile': str(source), 'artifactFile': str(artifact),
            'sourceSha256': source_hash, 'productionWrite': False, 'result': result}
        require_temporally_isolated_admission(admission, require_risk_profile=False)
        result_path = str(output / 'local-pre-admission.json')
        write_status(Path(result_path), admission)
    record = dict(row, source_sha256=source_hash, qualified=qualified, reason=reason,
        result_path=result_path, primary_result_path=str(output / 'primary.json'), production_write=False)
    write_status(output / 'checkpoint.json', {'manifest_sha256': manifest_hash, 'record': record,
        'source_contract_sha256': sha(output / 'source-contract.json'), 'financial_sha256': {p.name: sha(p) for p in (
            output / 'primary.json', output / 'primary.json.engine.json', output / 'holdout.json',
            output / 'local-pre-admission.json') if p.exists()}})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir', 'protocol',
             'engineering-dir', 'fit-oracle-dir', 'locked-oracle-dir', 'output-dir')
    for name in names:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in names:
        key = name.replace('-', '_')
        setattr(args, key, getattr(args, key).resolve())
    java_dir = Path(__file__).with_name('java')
    require_proof(args.fit_oracle_dir, java_dir, args.sim_repo)
    locked = read(args.locked_oracle_dir / 'audit.json')
    locked_manifest = read(args.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != sha(args.locked_oracle_dir / 'manifest.json')
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('unchanged twelve-case actual locked replay proof required')
    complete, engineering = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json'), read(args.engineering_dir / 'manifest.json')
    if (complete.get('completed') != 2 or complete.get('geometry_tests') != 9
            or complete['manifest_sha256'] != sha(args.engineering_dir / 'manifest.json')
            or complete.get('financial_validation_started') is not False or complete.get('production_write') is not False
            or engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_wick_geometry_candidate.py'))):
        raise ValueError('two repaired sources and nine geometry tests required')
    native = source_file(args.indsvr_repo)
    for name, digest in engineering['source_sha256'].items():
        if sha(native.with_name(name)) != digest:
            raise ValueError('frozen wick source/reference changed')
    reference_classes = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    for name, digest in engineering['reference_research_class_sha256'].items():
        if sha(reference_classes / name) != digest:
            raise ValueError('original risk/geometry reference bytecode changed')
    validator = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    if sha(validator) != engineering['source_validator_class_sha256']:
        raise ValueError('original validator bytecode changed')
    ready, protocol = read(args.input_dir / 'READY.json'), read(args.protocol)
    training = read(args.training_input_dir / 'READY.json')
    if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'wick_geometry_repair_v1'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('fixed source and pre-validation training protocols required')
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(args.input_dir / (symbol + suffix)) != ready['files'][symbol][key]:
                raise ValueError('frozen market input changed')
        if sha(args.training_input_dir / (symbol + '-15m.tsv')) != training['files'][symbol]['bars_sha256']:
            raise ValueError('frozen training input changed')
    queue = frozen_queue(native.read_text(encoding='utf-8'), ready['symbols'])
    helpers = [java_dir / name for name in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(output):
        if (output / 'FAILED.json').exists():
            raise ValueError('preserve and diagnose previous failure before resume')
        manifest = {'schema': 'frozen_wick_geometry_100_scopes_v1', 'queue': queue,
            'engineering_manifest_sha256': sha(args.engineering_dir / 'manifest.json'), 'native_source_sha256': sha(native),
            'protocol_sha256': sha(args.protocol), 'ready_sha256': sha(args.input_dir / 'READY.json'),
            'training_ready_sha256': sha(args.training_input_dir / 'READY.json'),
            'fit_oracle_manifest_sha256': sha(args.fit_oracle_dir / 'manifest.json'),
            'locked_oracle_manifest_sha256': locked['manifest_sha256'], 'wrapper_sha256': sha(Path(__file__)),
            'exporter_sha256': sha(Path(__file__).with_name('export_wick_geometry_candidate.py')),
            'helper_sha256': {p.name: sha(p) for p in helpers},
            'dependency_tools_sha256': {name: sha(Path(__file__).with_name(name)) for name in (
                'run_true_adx_batch.py', 'run_fit_risk_catalog_batch.py', 'verify_wick_geometry_repair.py',
                'run_fit_risk_admission.py', 'temporal_admission_contract.py', 'strategy_recovery_common.py')},
            'engineering_classes_sha256': {str(p.relative_to(args.engineering_dir / 'classes')): sha(p)
                for p in (args.engineering_dir / 'classes').rglob('*.class')},
            'mechanism_group': 'wick_rejection_confirmation', 'server_codegen_allowed': False, 'production_write': False}
        path = output / 'manifest.json'
        if path.exists() and read(path) != manifest:
            raise ValueError('frozen batch provenance changed')
        if not path.exists():
            write_status(path, manifest)
        manifest_hash = sha(path)
        classes = output / 'classes'
        classes.mkdir(exist_ok=True)
        cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
        parity_cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
            str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
        proof_records = {row['strategy']: row for row in read(args.engineering_dir / 'status.json')['records']}
        records = []
        try:
            execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(classes)] + list(map(str, helpers)), output / 'helper-compile.log')
            for row in queue:
                resources = resource_state(output)
                while not resources['ready']:
                    write_status(output / 'status.json', {'state': 'WAITING_FOR_LOCAL_RESOURCES', 'completed': len(records),
                        'total': 100, 'resources': resources, 'production_write': False})
                    time.sleep(10)
                    resources = resource_state(output)
                if sha(native) != manifest['native_source_sha256']:
                    raise ValueError('frozen native source changed during financial batch')
                record = run_case(args, row, manifest_hash, ready, protocol, cp, parity_cp, proof_records)
                records.append(record)
                write_status(output / 'results.json', records)
                write_status(output / 'status.json', {'state': 'RUNNING', 'updated_utc': datetime.now(timezone.utc).isoformat(),
                    'completed': len(records), 'total': 100, 'local_formal_qualified': sum(r['qualified'] for r in records),
                    'published': 0, 'production_write': False})
                print('WICK_GEOMETRY_FORMAL', len(records), '/', 100, row['strategy'], record['reason'], flush=True)
            write_status(output / 'FORMAL_COMPLETE.json', {'manifest_sha256': manifest_hash,
                'completed': 100, 'local_formal_qualified': sum(r['qualified'] for r in records), 'production_write': False})
        except Exception as error:
            write_status(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
            raise


if __name__ == '__main__':
    main()
