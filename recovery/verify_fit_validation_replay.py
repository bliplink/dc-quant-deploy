"""Training-only proof of actual four-profile fit/validation execution and future isolation."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from recovery.local_strategy_backtest import java_classpath, source_identity
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_offline_temporal_replay import FAMILIES, execute


WINDOWS = (('trend', 120, 30, 14), ('range', 90, 30, 14), ('breakout', 120, 20, 10))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def training_fixtures(original, target):
    """Private engineering inputs, never qualification scenes or new holdout prices."""
    target.mkdir(parents=True)
    bars, changed = target / 'BTCUSDT-15m.tsv', target / 'BTCUSDT-future-perturbed.tsv'
    count, perturbations = 0, 0
    with original.open('rb') as stream, bars.open('wb') as plain, changed.open('wb') as other:
        for line in stream:
            if not b'2023-01-01' <= line[:10] <= b'2023-12-31':
                continue
            count += 1
            plain.write(line)
            if line[:10] >= b'2023-05-01':
                values = line.decode('utf-8').rstrip('\r\n').split('\t')
                if len(values) != 6:
                    raise ValueError('unexpected training TSV shape')
                values[1:5] = [str(Decimal(value) * Decimal('1.2')) for value in values[1:5]]
                other.write(('\t'.join(values) + '\n').encode('utf-8'))
                perturbations += 1
            else:
                other.write(line)
    if count != 365 * 96 or perturbations != 245 * 96:
        raise ValueError('complete 2023 training year and untouched first 120 days required')
    scenes = {}
    for scene, *_ in WINDOWS:
        path = target / ('BTCUSDT-' + scene + '-engineering-scenes.tsv')
        point, stop, index = datetime(2022, 12, 31), datetime(2024, 1, 1), 0
        with path.open('w', encoding='utf-8', newline='\n') as stream:
            while point < stop:
                label = 'no_trade' if index % 5 == 4 else scene
                stream.write(point.isoformat(' ') + '\t' + label
                             + '\tSUCCESS\thistorical_kline_scene\tmarket_scene_v3_historical_kline_v1\n')
                point += timedelta(hours=12)
                index += 1
        scenes[scene] = path
    return bars, changed, scenes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sim-repo', 'training-input-dir', 'source-contract-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('sim_repo', 'training_input_dir', 'source_contract_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('each engineering attempt requires a fresh evidence directory')
    output.mkdir(parents=True)
    prerequisite = args.source_contract_dir / 'audit.json'
    previous = json.loads(prerequisite.read_text(encoding='utf-8'))
    if (previous.get('state') != 'complete' or previous.get('profile_signal_parity_cases') != 32
            or previous.get('actual_optimizer_cases') != 8
            or previous.get('manifest_sha256') != sha(args.source_contract_dir / 'manifest.json')):
        raise ValueError('complete source and optimizer prerequisite required')
    fixture = output / 'engineering-fixture-not-for-financial-qualification'
    original_bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    bars, changed, scenes = training_fixtures(original_bars, fixture)
    java_dir = Path(__file__).with_name('java')
    sources = [java_dir / name for name in ('OfflineTemporalReplayCli.java',
               'FitOnlyValidationReplayCli.java', 'FitOnlyValidationReplayOracleCli.java')]
    classes = output / 'classes'
    classes.mkdir()
    cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
    properties = args.sim_repo / 'config/application.properties'
    manifest = {'schema': 'actual_fit_validation_training_oracle_v1', 'begin': '2023-01-01',
        'end': '2023-12-31', 'future_perturbation_begin': '2023-05-01',
        'engineering_scene_fixture_only': True, 'parent_training_bars_sha256': sha(original_bars),
        'fixture_bars_sha256': sha(bars), 'perturbed_bars_sha256': sha(changed),
        'fixture_scenes_sha256': {key: sha(value) for key, value in scenes.items()},
        'source_contract_manifest_sha256': previous['manifest_sha256'],
        'java_source_sha256': {path.name: sha(path) for path in sources},
        'formal_class_sha256': {name: sha(args.sim_repo / 'target/classes/com/app/dc/service/simulation' / name)
            for name in ('runtime/SliceOptimizedWalkForwardRunner.class',
                         'runtime/VersionedBacktestRunner.class', 'BacktestOptimizationService.class')},
        'execution_properties_sha256': sha(properties), 'families': FAMILIES, 'windows': WINDOWS,
        'financial_validation_started': False, 'new_holdout_read': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
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
            for scene, fit, validate, forward in WINDOWS:
                case = output / 'cases' / family / scene
                case.mkdir(parents=True)
                policy = dict(request['optimizationProfile'], fitWindowDays=fit,
                              validateWindowDays=validate, forwardWindowDays=forward)
                spec = {'schema': 'offline_temporal_replay_v1', 'symbol': 'BTCUSDT', 'scene': scene,
                    'strategyName': item['strategyName'], 'strategyVersion': 'v1',
                    'beginDate': '2023-01-01', 'endDate': '2023-12-31', 'formalHoldout': False, 'trainingOnly': True,
                    'sourcePath': str(source), 'sourceSha256': hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                    'artifactPath': str(artifact), 'artifactSha256': sha(artifact),
                    'entryClass': package + '.' + class_name, 'lockedParameters': {'riskProfile': 0},
                    'candidateParameters': {'parameterSchema': request['parameterSchema'],
                        'defaultParams': request['defaultParameters'], 'optimizationProfile': policy},
                    'barsPath': str(bars), 'barsSha256': sha(bars), 'scenesPath': str(scenes[scene]),
                    'scenesSha256': sha(scenes[scene]), 'perturbedBarsPath': str(changed),
                    'perturbedBarsSha256': sha(changed)}
                atomic_write_json(case / 'spec.json', spec)
                execute(['java', '-Xmx768m', '-Duser.timezone=UTC', '-cp', cp,
                    'com.app.dc.service.simulation.FitOnlyValidationReplayOracleCli', str(case / 'spec.json'),
                    str(properties), str(case / 'result.json')], case / 'oracle.log')
                result = json.loads((case / 'result.json').read_text(encoding='utf-8'))
                if (result.get('passed') is not True or result.get('trades', 0) <= 0
                        or result.get('newHoldoutRead') is not False or result.get('productionWrite') is not False):
                    raise ValueError('actual nonzero-trade temporal isolation proof required')
                records.append(dict(family=family, scene=scene, folds=result['folds'], trades=result['trades'],
                                    selected_parameters=result['selectedParameters'], passed=True))
                atomic_write_json(output / 'status.json', {'completed': len(records), 'total': 9, 'records': records})
                print('FIT_VALIDATION_ORACLE', family, scene, 'folds', result['folds'], 'trades', result['trades'], flush=True)
        atomic_write_json(output / 'audit.json', {'state': 'complete', 'cases': len(records),
            'manifest_sha256': sha(output / 'manifest.json'), 'new_holdout_read': False,
            'financial_validation_started': False, 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'audit.json', {'state': 'failed', 'error': str(error), 'completed': len(records),
            'new_holdout_read': False, 'financial_validation_started': False, 'production_write': False})
        raise


if __name__ == '__main__':
    main()
