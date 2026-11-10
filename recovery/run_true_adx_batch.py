"""Frozen 200-scope actual-engine research for repaired fixed ADX sources; no server writes."""

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from recovery.export_true_adx_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.local_strategy_backtest import build_parameters, compile_source, java_classpath
from recovery.run_fit_risk_admission import require_proof
from recovery.strategy_recovery_common import atomic_write_json
from recovery.temporal_admission_contract import require_temporally_isolated_admission
from recovery.verify_fit_only_risk_contract import sha


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def execute(command, log, cwd=None):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd, timeout=1800)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('fixed ADX execution failed; preserve ' + str(log))
    return result.stdout


def frozen_queue(native, symbols):
    result = []
    for symbol in sorted(symbols):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            for side, selective in VARIANTS:
                source, item, descriptor = frozen_source(native, symbol, scene, side, selective)
                result.append(dict(descriptor, strategy=item['strategyName'], symbol=symbol, scene=scene))
    if len(result) != 200 or len({r['strategy'] for r in result}) != 200:
        raise ValueError('fixed ten symbols x five scenes x four directions required')
    return result


def completed_case(folder, manifest_hash):
    checkpoint = read(folder / 'checkpoint.json')
    if checkpoint['manifest_sha256'] != manifest_hash:
        raise ValueError('completed fixed-source observation belongs to another frozen batch')
    for name, digest in checkpoint['financial_sha256'].items():
        if sha(folder / name) != digest:
            raise ValueError('completed fixed-source financial output changed')
    contract = read(folder / 'source-contract.json')
    if (sha(folder / 'source-contract.json') != checkpoint['source_contract_sha256']
            or sha(Path(contract['source_path'])) != contract['source_sha256']
            or sha(Path(contract['artifact_path'])) != contract['artifact_sha256']
            or sha(Path(contract['source_path']).with_name('seed.json')) != contract['seed_sha256']
            or contract['source_sha256'] != checkpoint['record']['source_sha256']):
        raise ValueError('completed fixed-source source/artifact/seed changed')
    return checkpoint['record']


def run_case(args, row, manifest_hash, ready, protocol, cp, parity_cp, proof_records):
    output = args.output_dir / 'candidates' / row['strategy']
    if (output / 'checkpoint.json').exists():
        record = completed_case(output, manifest_hash)
        if any(record[key] != row[key] for key in ('strategy', 'symbol', 'scene', 'hypothesis', 'family')):
            raise ValueError('completed source scope mismatch')
        return record
    if output.exists():
        raise ValueError('partial source/financial attempt requires diagnosis; never blind replay: ' + str(output))
    output.mkdir(parents=True)
    frozen, item, descriptor = export_candidate(args.indsvr_repo, args.output_dir / 'frozen',
        row['symbol'], row['scene'], row['side'], row['selective'])
    source = frozen / 'GeneratedStrategy.java'
    previous = proof_records.get(row['strategy']) if row['symbol'] == 'BTCUSDT' and row['scene'] == 'trend' else None
    if previous:
        if previous['source_sha256'] != sha(source) or previous['artifact_sha256'] != sha(Path(previous['artifact_path'])):
            raise ValueError('canonical training contract artifact/source changed')
        artifact, entry = Path(previous['artifact_path']), previous['entry_class']
        signal_count = previous['signals']
    else:
        artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifact')
        execute(['java', '-Xmx256m', '-cp', parity_cp,
            'com.app.dc.service.strategy.research.TrueAdxRepairSignalParityCli', '--validate-source', str(source),
            item['request']['logicSummary'], row['strategy']], output / 'source-validator.log')
        text = execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', parity_cp,
            'com.app.dc.service.strategy.research.TrueAdxRepairSignalParityCli',
            str(args.training_input_dir / (row['symbol'] + '-15m.tsv')), row['symbol'], '2023-01-01', '2023-12-31',
            str(artifact), entry, row['strategy'], str(row['side']), str(row['selective']).lower()], output / 'training-signal-parity.log')
        match = re.search(r'TRUE_ADX_PARITY bars=(\d+) expectedSignals=(\d+) exportedSignals=(\d+) mismatches=(\d+)', text)
        if not match or int(match[1]) != 35040 or match[2] != match[3] or int(match[4]) != 0:
            raise ValueError('actual scoped compiled-source training parity failed')
        signal_count = int(match[2])
    source_hash = sha(source)
    atomic_write_json(output / 'source-contract.json', {'source_sha256': source_hash, 'artifact_sha256': sha(artifact),
        'source_path': str(source), 'artifact_path': str(artifact), 'seed_sha256': sha(frozen / 'seed.json'),
        'training_bars': 35040, 'training_signals': signal_count, 'nonzero_training_signal_coverage': signal_count > 0,
        'mismatches': 0, 'native_four_variant_nonzero_proof_reused': previous is not None, 'production_write': False})
    files = ready['files'][row['symbol']]
    spec = {'schema': 'offline_temporal_replay_v1', 'researchMode': 'fixed_full_primary',
        'strategyName': row['strategy'], 'strategyVersion': 'v1', 'symbol': row['symbol'], 'scene': row['scene'],
        'beginDate': protocol['primary_begin'], 'endDate': protocol['primary_end_inclusive'], 'formalHoldout': False,
        'protocolPath': str(args.protocol), 'protocolSha256': sha(args.protocol), 'lockedParameters': {},
        'sourcePath': str(source), 'sourceSha256': source_hash, 'artifactPath': str(artifact),
        'artifactSha256': sha(artifact), 'entryClass': entry, 'candidateParameters': build_parameters(item['request']),
        'barsPath': str(args.input_dir / (row['symbol'] + '-15m.tsv')), 'barsSha256': files['bars_sha256'],
        'scenesPath': str(args.input_dir / (row['symbol'] + '-scenes.tsv')), 'scenesSha256': files['scenes_sha256']}

    def run_cli(label, classname, specification):
        atomic_write_json(output / (label + '-spec.json'), specification)
        atomic_write_json(output / (label.upper() + '_STARTED.json'),
            {'manifest_sha256': manifest_hash, 'source_sha256': source_hash, 'never_repeat_as_parameter_search': True})
        execute(['java', '-Xmx768m', '-Duser.timezone=UTC', '-cp', cp,
            'com.app.dc.service.simulation.' + classname, str(output / (label + '-spec.json')),
            str(args.sim_repo / 'config/application.properties'), str(output / (label + '.json'))], output / (label + '.log'))
        return read(output / (label + '.json'))

    primary = run_cli('primary', 'FixedSourcePrimaryReplayCli', spec)
    qualified, reason, result_path = False, primary['qualificationReason'], None
    if primary['primaryQualified']:
        if primary['selectedParameters'] != {} or primary['parameterGridSearch'] is not False:
            raise ValueError('fixed-source representative parameter search changed')
        holdout = run_cli('holdout', 'OfflineTemporalReplayCli', dict(spec, researchMode='frozen_holdout',
            beginDate=protocol['holdout_begin'], endDate=protocol['holdout_end_inclusive'],
            primaryEndDate=protocol['primary_end_inclusive'], formalHoldout=True))
        qualified = holdout['passed']
        reason = 'qualified' if qualified else 'separate_chronological_holdout_failed'
        result = dict(primary['result'], admissionSchema='local_temporal_holdout_v2',
            beginDate=spec['beginDate'], endDate=spec['endDate'], selectedParameters={}, holdout=holdout,
            qualified=qualified, qualificationReason=reason, marketDataSource='local_ready_tsv')
        admission = {'mode': 'LOCAL_CODEX_TEMPORAL_PRE_ADMISSION', 'strategyName': row['strategy'],
            'symbol': row['symbol'], 'scene': row['scene'], 'sourceFile': str(source),
            'artifactFile': str(artifact), 'sourceSha256': source_hash, 'productionWrite': False, 'result': result}
        require_temporally_isolated_admission(admission, require_risk_profile=False)
        result_path = str(output / 'local-pre-admission.json')
        atomic_write_json(Path(result_path), admission)
    record = dict(row, source_sha256=source_hash, qualified=qualified, reason=reason,
        result_path=result_path, primary_result_path=str(output / 'primary.json'), production_write=False)
    atomic_write_json(output / 'checkpoint.json', {'manifest_sha256': manifest_hash, 'record': record,
        'source_contract_sha256': sha(output / 'source-contract.json'),
        'financial_sha256': {p.name: sha(p) for p in (output / 'primary.json', output / 'primary.json.engine.json',
            output / 'holdout.json', output / 'local-pre-admission.json') if p.exists()}})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir',
                 'protocol', 'engineering-dir', 'fit-oracle-dir', 'locked-oracle-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'reference_indsvr_repo', 'sim_repo', 'training_input_dir', 'input_dir',
                 'protocol', 'engineering_dir', 'fit_oracle_dir', 'locked_oracle_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    java_dir = Path(__file__).with_name('java')
    require_proof(args.fit_oracle_dir, java_dir, args.sim_repo)
    locked = read(args.locked_oracle_dir / 'audit.json')
    locked_manifest = read(args.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != sha(args.locked_oracle_dir / 'manifest.json')
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('exact actual-engine frozen-holdout proof required')
    complete = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json')
    engineering = read(args.engineering_dir / 'manifest.json')
    if (complete.get('completed') != 4 or complete.get('actual_reference_tests') != 8
            or complete['manifest_sha256'] != sha(args.engineering_dir / 'manifest.json')):
        raise ValueError('all four repaired sources and actual ADX reference proof required')
    native_path = source_file(args.indsvr_repo)
    for name, digest in engineering['source_sha256'].items():
        if sha(native_path.with_name(name)) != digest:
            raise ValueError('repaired source or engineering helper changed')
    if engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_true_adx_candidate.py')):
        raise ValueError('frozen true ADX exporter changed')
    validator = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    if sha(validator) != engineering['source_validator_class_sha256']:
        raise ValueError('unchanged source validator bytecode required')
    ready, protocol = read(args.input_dir / 'READY.json'), read(args.protocol)
    training = read(args.training_input_dir / 'READY.json')
    if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'true_adx_repair_v1'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('fixed source and pre-validation training protocols required')
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(args.input_dir / (symbol + suffix)) != ready['files'][symbol][key]:
                raise ValueError('frozen financial market input changed')
        if sha(args.training_input_dir / (symbol + '-15m.tsv')) != training['files'][symbol]['bars_sha256']:
            raise ValueError('training market input changed')
    queue = frozen_queue(native_path.read_text(encoding='utf-8'), ready['symbols'])
    helpers = [java_dir / name for name in ('OfflineTemporalReplayCli.java',
               'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    proof_records = {row['strategy']: row for row in read(args.engineering_dir / 'status.json')['records']}
    manifest = {'schema': 'fixed_true_adx_200_scope_research_v1', 'queue': queue,
        'engineering_manifest_sha256': sha(args.engineering_dir / 'manifest.json'),
        'native_source_sha256': sha(native_path), 'protocol_sha256': sha(args.protocol),
        'ready_sha256': sha(args.input_dir / 'READY.json'), 'training_ready_sha256': sha(args.training_input_dir / 'READY.json'),
        'fit_oracle_manifest_sha256': sha(args.fit_oracle_dir / 'manifest.json'),
        'locked_oracle_manifest_sha256': locked['manifest_sha256'], 'wrapper_sha256': sha(Path(__file__)),
        'exporter_sha256': sha(Path(__file__).with_name('export_true_adx_candidate.py')),
        'helper_sha256': {p.name: sha(p) for p in helpers},
        'engineering_classes_sha256': {p.name: sha(p) for p in (args.engineering_dir / 'classes').rglob('*.class')},
        'mechanism_groups_not_four_independent_strategies': 1, 'production_write': False, 'server_codegen_allowed': False}
    manifest_path = output / 'manifest.json'
    if manifest_path.exists() and read(manifest_path) != manifest:
        raise ValueError('research batch inputs changed; preserve prior observations')
    atomic_write_json(manifest_path, manifest)
    classes = output / 'classes'
    classes.mkdir(exist_ok=True)
    cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
    parity_cp = os.pathsep.join([str(args.engineering_dir / 'classes'),
        str(args.reference_indsvr_repo / 'target/test-classes'), str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    records = []
    try:
        execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                 '-d', str(classes)] + list(map(str, helpers)), output / 'helper-compile.log')
        for row in queue:
            if sha(native_path) != manifest['native_source_sha256']:
                raise ValueError('frozen native source changed during financial batch')
            record = run_case(args, row, sha(manifest_path), ready, protocol, cp, parity_cp, proof_records)
            records.append(record)
            atomic_write_json(output / 'results.json', records)
            atomic_write_json(output / 'status.json', {'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'completed': len(records), 'total': 200, 'local_formal_qualified': sum(r['qualified'] for r in records),
                'published': 0, 'errors': [], 'production_write': False})
            print('TRUE_ADX_FORMAL', len(records), '/', 200, row['strategy'], record['reason'], flush=True)
        atomic_write_json(output / 'FORMAL_COMPLETE.json', {'manifest_sha256': sha(manifest_path),
            'completed': len(records), 'local_formal_qualified': sum(r['qualified'] for r in records), 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
