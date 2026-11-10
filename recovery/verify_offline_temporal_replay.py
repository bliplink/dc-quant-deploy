"""Engineering-only 2023 replay oracle; never reads the new chronological holdout."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from recovery.local_strategy_backtest import java_classpath, source_identity
from recovery.strategy_recovery_common import atomic_write_json


FAMILIES = ('TrendPullbackHypothesis', 'RsiAtrEnvelopeReentryLongHypothesis', 'SceneControlledBreakoutHypothesis')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('training-only replay oracle failed; preserve ' + str(log))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sim-repo', 'indsvr-repo', 'training-input-dir', 'source-contract-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('sim_repo', 'indsvr_repo', 'training_input_dir', 'source_contract_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('each engineering attempt requires a new evidence directory')
    output.mkdir(parents=True)
    previous = json.loads((args.source_contract_dir / 'audit.json').read_text(encoding='utf-8'))
    if previous.get('state') != 'complete' or previous.get('profile_signal_parity_cases') != 32:
        raise ValueError('completed source/parameter parity prerequisite missing')
    fixture = output / 'engineering-fixture-not-for-financial-qualification'
    fixture.mkdir()
    original_bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    bars = fixture / 'BTCUSDT-15m.tsv'
    with original_bars.open('rb') as stream, bars.open('wb') as target:
        for line in stream:
            if b'2023-05-01' <= line[:10] <= b'2023-07-01':
                target.write(line)
    scenes = fixture / 'BTCUSDT-scenes.tsv'
    with scenes.open('w', encoding='utf-8', newline='\n') as stream:
        point, stop = datetime(2023, 4, 30), datetime(2023, 7, 2)
        while point < stop:
            stream.write(point.isoformat(' ') + '\ttrend\tSUCCESS\thistorical_kline_scene\tmarket_scene_v3_historical_kline_v1\n')
            point += timedelta(hours=12)
    java_dir = Path(__file__).with_name('java')
    sources = [java_dir / name for name in ('OfflineTemporalReplayCli.java', 'OfflineTemporalReplayOracleCli.java')]
    classes = output / 'classes'
    classes.mkdir()
    cp = str(classes) + os.pathsep + java_classpath(args.sim_repo) + os.pathsep + str(args.indsvr_repo / 'target/classes')
    properties = args.sim_repo / 'config/application.properties'
    atomic_write_json(output / 'manifest.json', {'schema': 'offline_temporal_engineering_oracle_v1',
        'begin': '2023-05-01', 'end': '2023-07-01', 'engineering_scene_fixture_only': True,
        'parent_training_bars_sha256': sha(original_bars), 'fixture_bars_sha256': sha(bars),
        'fixture_scenes_sha256': sha(scenes), 'source_contract_manifest_sha256': previous['manifest_sha256'],
        'java_source_sha256': {path.name: sha(path) for path in sources},
        'execution_properties_sha256': sha(properties), 'families': FAMILIES,
        'live_registry_class_sha256': sha(args.indsvr_repo / 'target/classes/com/app/dc/service/strategy/runtime/StrategyLiveRegistryRow.class'),
        'financial_validation_started': False, 'new_holdout_read': False, 'production_write': False})
    records = []
    try:
        execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                 '-d', str(classes)] + list(map(str, sources)), output / 'compile.log')
        seeds = [json.loads(path.read_text(encoding='utf-8'))['strategies'][0]
                 for path in (args.source_contract_dir / 'frozen').glob('*/seed.json')]
        for family in FAMILIES:
            item = next(row for row in seeds if row['request']['logicSummary'].split(';')[0] == 'FitOnlyRisk' + family)
            source = args.source_contract_dir / 'frozen' / item['strategyName'] / 'GeneratedStrategy.java'
            artifact = args.source_contract_dir / 'artifacts' / family / 'strategy.jar'
            package, class_name = source_identity(source.read_text(encoding='utf-8'))
            request = item['request']
            for profile in range(4):
                case = output / 'cases' / family / str(profile)
                case.mkdir(parents=True)
                spec = {'schema': 'offline_temporal_replay_v1', 'symbol': 'BTCUSDT', 'scene': 'trend',
                    'strategyName': item['strategyName'], 'strategyVersion': 'v1',
                    'beginDate': '2023-05-01', 'endDate': '2023-07-01', 'formalHoldout': False,
                    'sourcePath': str(source), 'sourceSha256': sha(source),
                    'artifactPath': str(artifact), 'artifactSha256': sha(artifact),
                    'entryClass': package + '.' + class_name, 'lockedParameters': {'riskProfile': profile},
                    'candidateParameters': {'parameterSchema': request['parameterSchema'],
                        'defaultParams': request['defaultParameters'], 'optimizationProfile': request['optimizationProfile']},
                    'barsPath': str(bars), 'barsSha256': sha(bars), 'scenesPath': str(scenes),
                    'scenesSha256': sha(scenes), 'fixtureDir': str(fixture)}
                atomic_write_json(case / 'spec.json', spec)
                execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', cp,
                    'com.app.dc.service.simulation.OfflineTemporalReplayOracleCli', str(case / 'spec.json'),
                    str(properties), str(case / 'result.json')], case / 'oracle.log')
                result = json.loads((case / 'result.json').read_text(encoding='utf-8'))
                if (result.get('passed') is not True or result['tradeCount'] <= 0
                        or result.get('productionWrite') is not False):
                    raise ValueError('oracle requires actual nonzero-trade parity')
                records.append({'family': family, 'profile': profile, 'trades': result['tradeCount'], 'passed': True})
                atomic_write_json(output / 'status.json', {'completed': len(records), 'total': 12, 'records': records})
                print('LOCKED_REPLAY_ORACLE', family, profile, 'trades', result['tradeCount'], flush=True)
        atomic_write_json(output / 'audit.json', {'state': 'complete', 'cases': len(records),
            'manifest_sha256': sha(output / 'manifest.json'), 'new_holdout_read': False,
            'financial_validation_started': False, 'production_write': False,
            'publisher_parameter_function_verified': True, 'real_database_persistence_verified': False})
    except Exception as error:
        atomic_write_json(output / 'audit.json', {'state': 'failed', 'error': str(error), 'completed': len(records),
            'new_holdout_read': False, 'financial_validation_started': False, 'production_write': False})
        raise


if __name__ == '__main__':
    main()
