"""Frozen OHLCV-proxy scopes -> unchanged actual primary -> strict policy -> disjoint holdout; never publishes."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import time

import psutil

from recovery.export_ohlcv_profile_proxy_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.local_strategy_backtest import build_parameters, compile_source, java_classpath
from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_catalog_batch import exclusive_batch, resource_state, write_status
from recovery.run_true_adx_batch import completed_case, read
from recovery.strict_primary_admission import adjudicate_primary
from recovery.temporal_admission_contract import require_temporally_isolated_admission
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute
from recovery.watch_fixed_primary_supplements import parent_alive


def frozen_queue(native, symbols):
    if len(symbols) != 10 or len(set(symbols)) != 10:
        raise ValueError('exactly ten distinct frozen symbols required')
    queue = []
    for symbol in sorted(symbols):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            for mode, side in VARIANTS:
                _, item, descriptor = frozen_source(native, symbol, scene, side, mode)
                queue.append(dict(descriptor, strategy=item['strategyName'], symbol=symbol, scene=scene))
    if len(queue) != 200 or len({r['strategy'] for r in queue}) != 200:
        raise ValueError('exact 200 unique scopes, not 200 independent mechanisms, required')
    return queue


def strict_primary(primary, profile):
    audit = adjudicate_primary(primary['result'], profile)
    return bool(primary['primaryQualified'] and audit['qualified']), audit


def require_parent_complete(parent):
    directory = Path(parent['output_dir'])
    manifest, marker = read(directory / 'manifest.json'), read(directory / 'BATCH_COMPLETE.json')
    queue = manifest.get('queue', [])
    if (sha(directory / 'manifest.json') != parent['manifest_sha256']
            or marker.get('manifest_sha256') != parent['manifest_sha256']
            or marker.get('completed') != 400 or marker.get('production_write') is not False
            or len(queue) != 400 or len({row['strategy'] for row in queue}) != 400
            or (directory / 'FAILED.json').exists()):
        raise ValueError('parent must genuinely finish400, not disappear or fail')


def run_case(args, row, manifest_hash, ready, protocol, cp, parity_cp, proof_records,
             *, export_source=None, scope_fields=None, training_proof_resolver=None):
    output = args.output_dir / 'candidates' / row['strategy']
    if (output / 'checkpoint.json').exists():
        saved = completed_case(output, manifest_hash)
        fields = scope_fields or ('strategy', 'symbol', 'scene', 'hypothesis', 'family', 'mechanism_group', 'mode', 'side')
        if any(saved[k] != row[k] for k in fields):
            raise ValueError('completed source scope/event changed')
        return saved
    if output.exists():
        raise ValueError('partial attempt: diagnose without replay: ' + str(output))
    output.mkdir(parents=True)
    if export_source is None:
        frozen, item, _ = export_candidate(args.indsvr_repo, args.output_dir / 'frozen',
            row['symbol'], row['scene'], row['side'], row['mode'])
    else:
        frozen, item, _ = export_source(args, row)
    source = frozen / 'GeneratedStrategy.java'
    if training_proof_resolver is not None:
        original = training_proof_resolver(row, source, frozen / 'seed.json')
        if not original or 'training_proof_receipt' not in original or 'training_proof_receipt_sha256' not in original:
            raise ValueError('explicit complete training proof required; never fall back to a different source')
    else:
        original = proof_records.get(row['strategy']) if row['symbol'] == 'BTCUSDT' and row['scene'] == 'trend' else None
    if original:
        artifact, entry = Path(original['artifact_path']), original['entry_class']
        if original['source_sha256'] != sha(source) or original['artifact_sha256'] != sha(artifact):
            raise ValueError('canonical proxy source/artifact changed')
        signals = original['signals']
    else:
        artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifact')
        execute(['java', '-Xmx256m', '-cp', parity_cp,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source', str(source),
            item['request']['logicSummary'], row['strategy']], output / 'source-validator.log')
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', parity_cp,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
            str(args.training_input_dir / (row['symbol'] + '-15m.tsv')), row['symbol'], '2023-01-01', '2023-12-31',
            row['hypothesis'], str(artifact), entry], output / 'training-signal-parity.log')
        found = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
        if not found or int(found[1]) != 35040 or found[2] != found[3] or int(found[4]) != 0:
            raise ValueError('scoped original-CLI source parity failed')
        signals = int(found[2])
    source_hash = sha(source)
    source_contract = {'source_path': str(source), 'source_sha256': source_hash,
        'artifact_path': str(artifact), 'artifact_sha256': sha(artifact), 'seed_sha256': sha(frozen / 'seed.json'),
        'training_bars': 35040, 'training_signals': signals, 'nonzero_training_signal_coverage': signals > 0,
        'mismatches': 0, 'canonical_proof_reused': original is not None, 'production_write': False}
    if training_proof_resolver is not None:
        from recovery.cusum_training_consumer import require_receipt
        receipt = require_receipt(original, row, source, frozen / 'seed.json', artifact, signals)
        source_contract.update(training_proof_receipt=receipt,
            training_proof_receipt_sha256=original['training_proof_receipt_sha256'])
    write_status(output / 'source-contract.json', source_contract)
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
    admitted, audit = strict_primary(primary, item['request']['optimizationProfile'])
    write_status(output / 'strict-primary-admission.json', audit)
    qualified, reason, result_path = False, (primary['qualificationReason'] if not primary['primaryQualified'] else audit['reason']), None
    if admitted:
        if primary['selectedParameters'] != {} or primary['parameterGridSearch'] is not False:
            raise ValueError('fixed representative parameters changed')
        holdout = replay('holdout', 'OfflineTemporalReplayCli', dict(spec, researchMode='frozen_holdout',
            beginDate=protocol['holdout_begin'], endDate=protocol['holdout_end_inclusive'],
            primaryEndDate=protocol['primary_end_inclusive'], formalHoldout=True))
        qualified, reason = holdout['passed'], 'qualified' if holdout['passed'] else 'separate_chronological_holdout_failed'
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
            output / 'primary.json', output / 'primary.json.engine.json', output / 'strict-primary-admission.json',
            output / 'holdout.json', output / 'local-pre-admission.json') if p.exists()}})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir', 'protocol',
             'engineering-dir', 'regression-dir', 'fit-oracle-dir', 'locked-oracle-dir', 'output-dir')
    for name in names:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--wait-for-parent-pid', type=int)
    parser.add_argument('--wait-for-parent-dir', type=Path)
    args = parser.parse_args()
    for name in names:
        key = name.replace('-', '_'); setattr(args, key, getattr(args, key).resolve())
    java_dir = Path(__file__).with_name('java')
    require_proof(args.fit_oracle_dir, java_dir, args.sim_repo)
    locked, locked_manifest = read(args.locked_oracle_dir / 'audit.json'), read(args.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != sha(args.locked_oracle_dir / 'manifest.json')
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('unchanged twelve-case actual locked replay proof required')
    complete, engineering = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json'), read(args.engineering_dir / 'manifest.json')
    regression = read(args.regression_dir / 'audit.json')
    if (complete.get('completed') != 4 or complete.get('mathematics_tests') != 12 or complete.get('independent_histogram_fixtures') != 64
            or complete['manifest_sha256'] != sha(args.engineering_dir / 'manifest.json')
            or complete.get('financial_validation_started') is not False or complete.get('production_write') is not False
            or engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_ohlcv_profile_proxy_candidate.py'))
            or engineering['protocol_sha256'] != sha(args.protocol)
            or engineering['training_ready_sha256'] != sha(args.training_input_dir / 'READY.json')
            or regression.get('state') != 'complete' or regression['manifest_sha256'] != sha(args.regression_dir / 'manifest.json')
            or regression['regression_log_sha256'] != sha(args.regression_dir / 'full-research-regression.log')
            or read(args.regression_dir / 'manifest.json')['engineering_manifest_sha256'] != complete['manifest_sha256']):
        raise ValueError('complete four-source mathematics/64-oracle/regression proof required')
    native = source_file(args.indsvr_repo)
    for name, digest in engineering['source_sha256'].items():
        if sha(native.with_name(name)) != digest:
            raise ValueError('frozen source/catalog changed')
    for relative, expected in complete['class_sha256'].items():
        if sha(args.engineering_dir / 'classes' / relative) != expected:
            raise ValueError('frozen engineering bytecode changed')
    reference = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    if sha(reference) != engineering['source_validator_class_sha256']:
        raise ValueError('original validator changed')
    original_cli = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    if sha(original_cli) != engineering['original_parity_cli_sha256']:
        raise ValueError('original parity CLI changed')
    ready, protocol, training = read(args.input_dir / 'READY.json'), read(args.protocol), read(args.training_input_dir / 'READY.json')
    if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'ohlcv_profile_proxy_v1'
            or protocol.get('mechanism_group') != 'ohlcv_distribution_auction'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('fixed source and untouched temporal/training policies required')
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(args.input_dir / (symbol + suffix)) != ready['files'][symbol][key]:
                raise ValueError('frozen market input changed')
        if sha(args.training_input_dir / (symbol + '-15m.tsv')) != training['files'][symbol]['bars_sha256']:
            raise ValueError('frozen training input changed')
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(output):
        if (output / 'FAILED.json').exists():
            raise ValueError('preserve prior failure before explicit diagnosis')
        previous = read(output / 'manifest.json') if (output / 'manifest.json').exists() else None
        parent = previous.get('parent_identity') if previous else None
        if args.wait_for_parent_pid:
            if parent is None:
                process = psutil.Process(args.wait_for_parent_pid); command = process.cmdline()
                if (not args.wait_for_parent_dir or '-m' not in command or '--output-dir' not in command
                        or command[command.index('-m') + 1] != 'recovery.run_fit_risk_scope_batch'
                        or Path(command[command.index('--output-dir') + 1]).resolve() != args.wait_for_parent_dir.resolve()):
                    raise ValueError('explicit balanced queue parent identity required')
                parent = {'pid': process.pid, 'create_time': process.create_time(), 'command': command,
                    'output_dir': str(args.wait_for_parent_dir.resolve()),
                    'manifest_sha256': sha(args.wait_for_parent_dir / 'manifest.json')}
            if parent['pid'] != args.wait_for_parent_pid:
                raise ValueError('bound parent changed')
        elif parent is not None:
            raise ValueError('resume with original parent binding')
        helpers = [java_dir / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
        queue = frozen_queue(native.read_text(encoding='utf-8'), ready['symbols'])
        manifest = {'schema': 'frozen_ohlcv_profile_proxy_200_scopes_v1', 'queue': queue, 'parent_identity': parent,
            'engineering_manifest_sha256': sha(args.engineering_dir / 'manifest.json'), 'regression_manifest_sha256': sha(args.regression_dir / 'manifest.json'),
            'native_source_sha256': sha(native), 'protocol_sha256': sha(args.protocol), 'ready_sha256': sha(args.input_dir / 'READY.json'),
            'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'fit_oracle_manifest_sha256': sha(args.fit_oracle_dir / 'manifest.json'),
            'locked_oracle_manifest_sha256': locked['manifest_sha256'], 'wrapper_sha256': sha(Path(__file__)),
            'exporter_sha256': sha(Path(__file__).with_name('export_ohlcv_profile_proxy_candidate.py')),
            'helper_sha256': {p.name: sha(p) for p in helpers},
            'dependency_tools_sha256': {n: sha(Path(__file__).with_name(n)) for n in (
                'run_true_adx_batch.py', 'run_fit_risk_catalog_batch.py', 'verify_ohlcv_profile_proxy.py', 'strict_primary_admission.py',
                'run_fit_risk_admission.py', 'temporal_admission_contract.py', 'strategy_recovery_common.py')},
            'engineering_classes_sha256': complete['class_sha256'], 'mechanism_group': 'ohlcv_distribution_auction',
            'server_codegen_allowed': False, 'production_write': False}
        if previous is not None and previous != manifest:
            raise ValueError('frozen batch provenance changed')
        if previous is None: write_status(output / 'manifest.json', manifest)
        manifest_hash = sha(output / 'manifest.json')
        if parent:
            while parent_alive(parent):
                write_status(output / 'status.json', {'state': 'WAITING_FOR_BOUND_BALANCED_BATCH',
                    'completed': 0, 'total': 200, 'parent_pid': parent['pid'], 'production_write': False})
                time.sleep(10)
            require_parent_complete(parent)
        classes = output / 'classes'; classes.mkdir(exist_ok=True)
        cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
        parity_cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
            str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
        proof_records = {r['strategy']: r for r in read(args.engineering_dir / 'status.json')['records']}
        records = []
        try:
            execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(classes)] + list(map(str, helpers)), output / 'helper-compile.log')
            for row in queue:
                resources = resource_state(output)
                while not resources['ready']:
                    write_status(output / 'status.json', {'state': 'WAITING_FOR_LOCAL_RESOURCES', 'completed': len(records),
                        'total': 200, 'resources': resources, 'production_write': False})
                    time.sleep(10); resources = resource_state(output)
                if sha(native) != manifest['native_source_sha256']: raise ValueError('frozen native source changed')
                record = run_case(args, row, manifest_hash, ready, protocol, cp, parity_cp, proof_records)
                records.append(record)
                write_status(output / 'results.json', records)
                write_status(output / 'status.json', {'state': 'RUNNING', 'updated_utc': datetime.now(timezone.utc).isoformat(),
                    'completed': len(records), 'total': 200, 'local_formal_qualified': sum(r['qualified'] for r in records),
                    'published': 0, 'production_write': False})
                print('OHLCV_PROFILE_FORMAL', len(records), '/', 200, row['strategy'], record['reason'], flush=True)
            write_status(output / 'FORMAL_COMPLETE.json', {'manifest_sha256': manifest_hash,
                'completed': 200, 'local_formal_qualified': sum(r['qualified'] for r in records), 'production_write': False})
        except Exception as error:
            write_status(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False}); raise


if __name__ == '__main__':
    main()
