"""Local-only fit/validate -> unchanged primary -> frozen-parameter separate holdout."""

import argparse
import json
import math
import os
from decimal import Decimal
from pathlib import Path

from recovery.local_strategy_backtest import build_parameters, java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.temporal_admission_contract import require_temporally_isolated_admission
from recovery.verify_fit_only_risk_contract import execute, sha


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_proof(directory, java_dir, sim_repo):
    audit, manifest = read(directory / 'audit.json'), read(directory / 'manifest.json')
    if (audit.get('state') != 'complete' or audit.get('cases') != 9
            or audit.get('manifest_sha256') != sha(directory / 'manifest.json')
            or audit.get('production_write') is not False or audit.get('new_holdout_read') is not False):
        raise ValueError('completed nine-case actual fit/validation oracle required')
    for name, digest in manifest['java_source_sha256'].items():
        if sha(java_dir / name) != digest:
            raise ValueError('oracle helper source changed: ' + name)
    for name, digest in manifest['formal_class_sha256'].items():
        if sha(sim_repo / 'target/classes/com/app/dc/service/simulation' / name) != digest:
            raise ValueError('formal engine bytecode changed')
    if manifest['execution_properties_sha256'] != sha(sim_repo / 'config/application.properties'):
        raise ValueError('formal execution settings changed')
    cases = list((directory / 'cases').glob('*/*/result.json'))
    if len(cases) != 9:
        raise ValueError('missing actual fit oracle results')
    for path in cases:
        item = read(path)
        if (item.get('passed') is not True or item.get('trades', 0) <= 0
                or item.get('exactValidationTradesAndFitChoices') is not True
                or item.get('forwardFenceRejected') is not True
                or item.get('firstFitFuturePerturbationInvariant') is not True
                or item.get('productionWrite') is not False or item.get('newHoldoutRead') is not False):
            raise ValueError('incomplete actual fit oracle case')
    return audit['manifest_sha256']


def validation_passes(result):
    """Only necessary existing validation gates. Forward/OOS remain entirely withheld."""
    for key in ('tradeCount', 'profitFactor', 'maxDrawdownPct', 'feeAdjustedValidatePnl'):
        value = result.get(key)
        if isinstance(value, bool) or value is None or not math.isfinite(float(value)):
            raise ValueError('invalid validation metric: ' + key)
    if result.get('forwardMetrics') != 'WITHHELD' or result.get('fullPeriodSafety') != 'WITHHELD':
        raise ValueError('screen executed or exposed withheld metrics')
    return (result['tradeCount'] >= 20 and Decimal(str(result['profitFactor'])) >= Decimal('1.20')
            and Decimal(str(result['maxDrawdownPct'])) <= Decimal('0.15')
            and Decimal(str(result['feeAdjustedValidatePnl'])) > 0)


def compare_primary_validation(screen, primary):
    for key in ('tradeCount', 'profitFactor', 'maxDrawdownPct', 'feeAdjustedValidatePnl'):
        if screen[key] != primary['result'][key]:
            raise ValueError('unchanged primary/validation screen mismatch: ' + key)
    if screen['selectedParameters'] != primary['selectedParameters']:
        raise ValueError('representative parameter selection changed after forward replay')
    original = [trade for row in screen['sliceResults'] for trade in row['validateTrades']]
    if original != primary['result']['tradeList']:
        raise ValueError('primary validation trades changed after forward replay')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('contract-dir', 'input-dir', 'protocol', 'sim-repo', 'oracle-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--strategy', required=True)
    args = parser.parse_args()
    for name in ('contract_dir', 'input_dir', 'protocol', 'sim_repo', 'oracle_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.output_dir.exists():
        raise ValueError('use a fresh directory; inspected results cannot be rerun as parameter search')
    java_dir = Path(__file__).with_name('java')
    proof_hash = require_proof(args.oracle_dir, java_dir, args.sim_repo)
    contract = read(args.contract_dir / 'artifacts' / args.strategy / 'contract.json')
    original = args.contract_dir / 'frozen' / args.strategy
    source = original / 'GeneratedStrategy.java'
    artifact = Path(contract['artifact_path'])
    profiles = contract['profiles']
    if (contract['manifest_sha256'] != sha(args.contract_dir / 'manifest.json')
            or contract.get('source_validator_passed') is not True
            or contract['source_sha256'] != sha(source) or contract['artifact_sha256'] != sha(artifact)
            or [row['risk_profile'] for row in profiles] != [0, 1, 2, 3]
            or any(row['bars'] != 35040 or row['mismatches'] != 0 for row in profiles)):
        raise ValueError('source-bound four-profile training parity required')
    seed = read(original / 'seed.json')
    item = seed['strategies'][0]
    if item['strategyName'] != args.strategy or not contract['family'].startswith('FitOnlyRisk'):
        raise ValueError('source contract scope mismatch')
    protocol, ready = read(args.protocol), read(args.input_dir / 'READY.json')
    if (protocol.get('protocol_version') != 'temporal_source_research_v2'
            or protocol.get('risk_profiles') != [0, 1, 2, 3]
            or ready['protocol_sha256'] != sha(args.protocol)):
        raise ValueError('frozen temporal protocol and data are required')
    files, symbol = ready['files'][item['symbol']], item['symbol']
    for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
        if sha(args.input_dir / (symbol + suffix)) != files[key]:
            raise ValueError('frozen market inputs changed')
    output = args.output_dir
    output.mkdir(parents=True)
    frozen = output / 'frozen' / args.strategy
    frozen.mkdir(parents=True)
    (frozen / 'GeneratedStrategy.java').write_bytes(source.read_bytes())
    atomic_write_json(frozen / 'seed.json', seed)
    helpers = [java_dir / name for name in ('OfflineTemporalReplayCli.java',
               'FitOnlyValidationReplayCli.java', 'FitOnlyPrimaryReplayCli.java')]
    atomic_write_json(output / 'manifest.json', {'schema': 'fit_risk_local_temporal_admission_v1',
        'strategy': args.strategy, 'contract_sha256': sha(args.contract_dir / 'artifacts' / args.strategy / 'contract.json'),
        'source_sha256': sha(source), 'artifact_sha256': sha(artifact), 'protocol_sha256': sha(args.protocol),
        'ready_sha256': sha(args.input_dir / 'READY.json'), 'fit_validation_oracle_manifest_sha256': proof_hash,
        'helper_sha256': {path.name: sha(path) for path in helpers}, 'production_write': False})
    classes = output / 'classes'
    classes.mkdir()
    cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
    execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
             '-d', str(classes)] + list(map(str, helpers)), output / 'compile.log')
    spec = {'schema': 'offline_temporal_replay_v1', 'researchMode': 'validation_only',
        'strategyName': args.strategy, 'strategyVersion': item['sourceStrategyVersion'],
        'symbol': symbol, 'scene': item['scene'], 'beginDate': protocol['primary_begin'],
        'endDate': protocol['primary_end_inclusive'], 'formalHoldout': False,
        'protocolPath': str(args.protocol), 'protocolSha256': sha(args.protocol),
        'sourcePath': str(frozen / 'GeneratedStrategy.java'), 'sourceSha256': sha(source),
        'artifactPath': str(artifact), 'artifactSha256': sha(artifact), 'entryClass': contract['entry_class'],
        'candidateParameters': build_parameters(item['request']), 'lockedParameters': {'riskProfile': 0},
        'barsPath': str(args.input_dir / (symbol + '-15m.tsv')), 'barsSha256': files['bars_sha256'],
        'scenesPath': str(args.input_dir / (symbol + '-scenes.tsv')), 'scenesSha256': files['scenes_sha256']}
    properties = args.sim_repo / 'config/application.properties'

    def run_cli(label, classname, specification):
        atomic_write_json(output / (label + '-spec.json'), specification)
        atomic_write_json(output / (label.upper() + '_STARTED.json'),
            {'manifest_sha256': sha(output / 'manifest.json'), 'never_repeat_as_parameter_search': True})
        execute(['java', '-Xmx768m', '-Duser.timezone=UTC', '-cp', cp,
            'com.app.dc.service.simulation.' + classname, str(output / (label + '-spec.json')),
            str(properties), str(output / (label + '.json'))], output / (label + '.log'))
        return read(output / (label + '.json'))

    screen = run_cli('validation', 'FitOnlyValidationReplayCli', spec)
    reason, qualified, envelope = 'validation_only_necessary_gate_failed', False, None
    if validation_passes(screen):
        primary = run_cli('primary', 'FitOnlyPrimaryReplayCli', dict(spec, researchMode='full_primary'))
        compare_primary_validation(screen, primary)
        reason = primary['qualificationReason']
        if primary['primaryQualified']:
            selected = primary['selectedParameters']
            if set(selected) != {'riskProfile'} or type(selected['riskProfile']) is not int or selected['riskProfile'] not in range(4):
                raise ValueError('actual primary selected invalid runtime profile')
            holdout = run_cli('holdout', 'OfflineTemporalReplayCli', dict(spec,
                researchMode='frozen_holdout', beginDate=protocol['holdout_begin'],
                endDate=protocol['holdout_end_inclusive'], primaryEndDate=protocol['primary_end_inclusive'],
                formalHoldout=True, lockedParameters=selected))
            qualified = holdout['passed']
            reason = 'qualified' if qualified else 'separate_chronological_holdout_failed'
            result = dict(primary['result'], admissionSchema='local_temporal_holdout_v2',
                beginDate=spec['beginDate'], endDate=spec['endDate'], selectedParameters=selected,
                holdout=holdout, qualified=qualified, qualificationReason=reason, marketDataSource='local_ready_tsv')
            envelope = {'mode': 'LOCAL_CODEX_TEMPORAL_PRE_ADMISSION', 'strategyName': args.strategy,
                'symbol': symbol, 'scene': item['scene'], 'sourceFile': str(frozen / 'GeneratedStrategy.java'),
                'artifactFile': str(artifact), 'sourceSha256': sha(source), 'productionWrite': False, 'result': result}
            require_temporally_isolated_admission(envelope)
            atomic_write_json(output / 'local-pre-admission.json', envelope)
    record = {'strategy': args.strategy, 'hypothesis': contract['hypothesis'], 'family': contract['family'],
        'symbol': symbol, 'scene': item['scene'], 'source_sha256': sha(source), 'qualified': qualified,
        'reason': reason, 'result_path': str(output / 'local-pre-admission.json') if envelope else None,
        'validation_fee_adjusted_pnl': screen['feeAdjustedValidatePnl'], 'production_write': False}
    atomic_write_json(output / 'results.json', [record])
    atomic_write_json(output / 'status.json', {'completed': 1, 'total': 1,
        'local_formal_qualified': int(qualified), 'published': 0, 'errors': []})
    atomic_write_json(output / 'FORMAL_COMPLETE.json', {'completed': 1,
        'manifest_sha256': sha(output / 'manifest.json'), 'local_formal_qualified': int(qualified),
        'results_sha256': sha(output / 'results.json'),
        'financial_outputs_sha256': {path.name: sha(path) for path in
            (output / 'validation.json', output / 'primary.json', output / 'holdout.json') if path.exists()},
        'production_write': False})
    print('FIT_RISK_LOCAL_ADMISSION', args.strategy, 'qualified', qualified, 'reason', reason, flush=True)


if __name__ == '__main__':
    main()
