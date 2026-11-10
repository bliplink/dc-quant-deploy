"""Add one disjoint holdout to an unchanged, already-passing fixed source; never rerun primary PnL."""

import argparse
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

from recovery import local_strategy_backtest as runner
from recovery.strategy_recovery_common import atomic_write_json
from recovery.temporal_admission_contract import require_temporally_isolated_admission


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_passing_fixed_primary(record, envelope, seed, protocol):
    result = envelope.get('result') or {}
    request = seed['strategies'][0]['request']
    if request.get('parameterSchema') or request.get('defaultParameters'):
        raise ValueError('this supplementary path only handles truly fixed parameters; fitted sources need the new primary runner')
    if (record.get('qualified') is not True or result.get('qualified') is not True
            or (result.get('holdout') or {}).get('passed') is not True
            or envelope.get('productionWrite') is not False
            or result.get('executionModelVersion') != 'v4_non_overlapping_walk_forward'
            or result.get('beginDate') != protocol['primary_begin']
            or result.get('endDate') != protocol['primary_end_inclusive']):
        raise ValueError('only completed primary and legacy-extra-holdout passes can receive a stricter supplementary test')
    if (result.get('oosPass') != 1 or result.get('tradeCount', 0) < 20
            or result.get('profitFactor', 0) < 1.20 or result.get('maxDrawdownPct', 1) > 0.15
            or result.get('feeAdjustedValidatePnl', 0) <= 0 or result.get('feeAdjustedForwardPnl', 0) <= 0
            or result.get('forwardContribution', 0) < max(0.20, result.get('minForwardContribution') or 0.20)
            or len(result.get('sliceResults') or []) < 3
            or any(json.loads(row.get('paramSetJson') or '{}') for row in result.get('optimizationTrials') or [])):
        raise ValueError('original financial gates or fixed-parameter evidence are missing; failed primaries remain consumed')


def execute(command, log):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('supplementary replay execution failed; preserve all evidence at ' + str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('formal-dir', 'input-dir', 'protocol', 'sim-repo', 'oracle-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--strategy', required=True)
    args = parser.parse_args()
    for name in ('formal_dir', 'input_dir', 'protocol', 'sim_repo', 'oracle_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('preserve the attempt and any consumed holdout; output must be new')
    protocol = json.loads(args.protocol.read_text(encoding='utf-8'))
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    if (protocol.get('protocol_version') != 'temporal_source_research_v2'
            or ready.get('protocol_sha256') != sha(args.protocol)
            or ready.get('holdout_begin') != protocol['holdout_begin']
            or ready.get('end') != protocol['holdout_end_inclusive']):
        raise ValueError('verified temporal input/protocol mismatch')
    rows = json.loads((args.formal_dir / 'results.json').read_text(encoding='utf-8'))
    record = next(row for row in rows if row['strategy'] == args.strategy)
    original_path = Path(record['result_path']).resolve()
    if not original_path.is_relative_to(args.formal_dir) or record['manifest_sha256'] != sha(args.formal_dir / 'manifest.json'):
        raise ValueError('primary financial provenance changed')
    envelope = json.loads(original_path.read_text(encoding='utf-8'))
    seed_path = args.formal_dir / 'frozen' / args.strategy / 'seed.json'
    seed = json.loads(seed_path.read_text(encoding='utf-8'))
    require_passing_fixed_primary(record, envelope, seed, protocol)
    source = Path(envelope['sourceFile']).read_text(encoding='utf-8')
    if hashlib.sha256(source.encode('utf-8')).hexdigest() != record['source_sha256']:
        raise ValueError('source changed since primary finance')
    oracle = json.loads((args.oracle_dir / 'audit.json').read_text(encoding='utf-8'))
    oracle_manifest = json.loads((args.oracle_dir / 'manifest.json').read_text(encoding='utf-8'))
    helper = Path(__file__).with_name('java') / 'OfflineTemporalReplayCli.java'
    if (oracle.get('state') != 'complete' or oracle.get('cases') != 12
            or oracle.get('manifest_sha256') != sha(args.oracle_dir / 'manifest.json')
            or oracle_manifest['java_source_sha256'][helper.name] != sha(helper)):
        raise ValueError('offline locked replay requires the exact completed actual-engine oracle')
    symbol = record['symbol']
    files = ready['files'][symbol]
    for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
        if sha(args.input_dir / (symbol + suffix)) != files[key]:
            raise ValueError('temporal market input changed')
    output.mkdir(parents=True)
    manifest = {'schema': 'fixed_source_supplementary_holdout_v1', 'strategy': args.strategy,
        'primary_envelope_sha256': sha(original_path), 'source_sha256': record['source_sha256'],
        'protocol_sha256': sha(args.protocol), 'ready_sha256': sha(args.input_dir / 'READY.json'),
        'oracle_manifest_sha256': oracle['manifest_sha256'], 'helper_source_sha256': sha(helper),
        'primary_pnl_rerun': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    frozen = output / 'frozen' / args.strategy
    frozen.mkdir(parents=True)
    (frozen / 'GeneratedStrategy.java').write_text(source, encoding='utf-8', newline='\n')
    atomic_write_json(frozen / 'seed.json', seed)
    artifact, entry_class, compiled_source = runner.compile_source(source, args.sim_repo, output / 'artifact')
    classes = output / 'helper-classes'
    classes.mkdir()
    cp = str(classes) + os.pathsep + runner.java_classpath(args.sim_repo)
    execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
             '-d', str(classes), str(helper)], output / 'helper-compile.log')
    item = seed['strategies'][0]
    if (item['strategyName'], item['symbol'], item['scene']) != (args.strategy, symbol, record['scene']):
        raise ValueError('fixed primary source scope changed')
    spec = {'schema': 'offline_temporal_replay_v1', 'strategyName': args.strategy,
        'strategyVersion': item['sourceStrategyVersion'], 'symbol': symbol, 'scene': record['scene'],
        'beginDate': protocol['holdout_begin'], 'endDate': protocol['holdout_end_inclusive'],
        'primaryEndDate': protocol['primary_end_inclusive'], 'formalHoldout': True,
        'sourcePath': str(frozen / 'GeneratedStrategy.java'), 'sourceSha256': record['source_sha256'],
        'artifactPath': str(artifact), 'artifactSha256': sha(artifact), 'entryClass': entry_class,
        'candidateParameters': runner.build_parameters(item['request']), 'lockedParameters': {},
        'barsPath': str(args.input_dir / (symbol + '-15m.tsv')), 'barsSha256': files['bars_sha256'],
        'scenesPath': str(args.input_dir / (symbol + '-scenes.tsv')), 'scenesSha256': files['scenes_sha256']}
    atomic_write_json(output / 'replay-spec.json', spec)
    atomic_write_json(output / 'HOLDOUT_STARTED.json', {'manifest_sha256': sha(output / 'manifest.json'),
        'source_sha256': record['source_sha256'], 'never_repeat_as_parameter_search': True})
    execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', cp,
        'com.app.dc.service.simulation.OfflineTemporalReplayCli', str(output / 'replay-spec.json'),
        str(args.sim_repo / 'config/application.properties'), str(output / 'holdout.json')], output / 'holdout.log')
    holdout = json.loads((output / 'holdout.json').read_text(encoding='utf-8'))
    admission = copy.deepcopy(envelope)
    admission.update(mode='LOCAL_CODEX_TEMPORAL_PRE_ADMISSION', sourceFile=str(compiled_source),
        artifactFile=str(artifact), sourceSha256=record['source_sha256'], primaryEnvelope=str(original_path))
    result = admission['result']
    result.update(admissionSchema='local_temporal_holdout_v2', selectedParameters={},
        bestParamSetJson='{}', holdout=holdout, qualified=holdout['passed'],
        qualificationReason='qualified' if holdout['passed'] else 'separate_chronological_holdout_failed')
    require_temporally_isolated_admission(admission, require_risk_profile=False)
    atomic_write_json(output / 'local-pre-admission.json', admission)
    derived_record = {**record, 'result_path': str(output / 'local-pre-admission.json'),
        'qualified': holdout['passed'], 'reason': result['qualificationReason'], 'requires_temporal_v2': True}
    atomic_write_json(output / 'results.json', [derived_record])
    status = {'completed': 1, 'total': 1, 'local_formal_qualified': int(holdout['passed']), 'published': 0, 'errors': []}
    atomic_write_json(output / 'status.json', status)
    atomic_write_json(output / 'FORMAL_COMPLETE.json', {'manifest_sha256': sha(output / 'manifest.json'),
        'completed': 1, 'local_formal_qualified': int(holdout['passed']), 'production_write': False})
    print('SUPPLEMENTARY_TEMPORAL_HOLDOUT', args.strategy, 'passed', holdout['passed'],
          'trades', holdout['tradeCount'], 'pf', holdout['profitFactor'], 'fee_adjusted', holdout['feeAdjustedPnl'])


if __name__ == '__main__':
    main()
