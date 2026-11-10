"""Prove repaired wick geometry, original risk/validator and actual compiled-source parity."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from recovery.export_wick_geometry_candidate import VARIANTS, export_candidate, source_file
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha


def execute(command, log, cwd=None):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd, timeout=900)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('wick engineering failed; preserve ' + str(log))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'reference_indsvr_repo', 'sim_repo', 'training_input_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('preserve every engineering attempt; fresh output required')
    native = source_file(args.indsvr_repo)
    sources = [native, native.with_name('WickGeometryRepairStrategyTest.java'), native.with_name('WickGeometryRepairSignalParityCli.java')]
    ready = json.loads((args.training_input_dir / 'READY.json').read_text(encoding='utf-8'))
    bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(bars) != ready['files']['BTCUSDT']['bars_sha256']):
        raise ValueError('untouched training data only')
    output.mkdir(parents=True)
    manifest = {'schema': 'wick_geometry_repair_engineering_v1', 'source_sha256': {path.name: sha(path) for path in sources},
        'source_validator_class_sha256': sha(args.reference_indsvr_repo /
            'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'),
        'reference_research_class_sha256': {name: sha(args.reference_indsvr_repo /
            'target/test-classes/com/app/dc/service/strategy/research' / name) for name in (
                'StrategyResearchBatchCli.class', 'StrategyResearchBatchCli$SceneWickReversalHypothesis.class',
                'StrategyResearchBatchCli$ExitPolicy.class')},
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'training_bars_sha256': sha(bars),
        'exporter_sha256': sha(Path(__file__).with_name('export_wick_geometry_candidate.py')),
        'wrapper_sha256': sha(Path(__file__)), 'training_begin': '2023-01-01', 'training_end': '2023-12-31',
        'mechanism_group': 'wick_rejection_confirmation', 'variants': list(VARIANTS),
        'financial_validation_started': False, 'forward_pnl_read': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    classes = output / 'classes'
    classes.mkdir()
    cp = os.pathsep.join([str(classes), str(args.reference_indsvr_repo / 'target/test-classes'),
        str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    records = []
    try:
        execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
            '-d', str(classes)] + list(map(str, sources)), output / 'compile.log')
        text = execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', cp, 'org.junit.runner.JUnitCore',
            'com.app.dc.service.strategy.research.WickGeometryRepairStrategyTest'], output / 'geometry-tests.log', args.indsvr_repo)
        if 'OK (9 tests)' not in text:
            raise ValueError('all nine geometry/decimal-boundary/causality/original-validator tests required')
        for side in VARIANTS:
            frozen, item, descriptor = export_candidate(args.indsvr_repo, output / 'frozen', 'BTCUSDT', 'trend', side)
            source = frozen / 'GeneratedStrategy.java'
            name = item['strategyName']
            artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifacts' / name)
            execute(['java', '-Xmx256m', '-cp', cp,
                'com.app.dc.service.strategy.research.WickGeometryRepairSignalParityCli', '--validate-source', str(source),
                item['request']['logicSummary'], name], output / 'logs' / (name + '-source.log'))
            text = execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', cp,
                'com.app.dc.service.strategy.research.WickGeometryRepairSignalParityCli', str(bars), 'BTCUSDT',
                '2023-01-01', '2023-12-31', str(artifact), entry, name, str(side)], output / 'logs' / (name + '-parity.log'))
            match = re.search(r'WICK_GEOMETRY_PARITY bars=(\d+) expectedSignals=(\d+) exportedSignals=(\d+) legacySignals=(\d+) mismatches=(\d+)', text)
            if not match or int(match[1]) != 35040 or int(match[2]) <= 0 or match[2] != match[3] or int(match[5]) != 0:
                raise ValueError('nonzero independent full-year geometry/source parity required')
            records.append(dict(descriptor, strategy=name, source_sha256=sha(source), artifact_sha256=sha(artifact),
                artifact_path=str(artifact), entry_class=entry, bars=int(match[1]), signals=int(match[2]),
                legacy_signals=int(match[4]), mismatches=0))
            atomic_write_json(output / 'status.json', {'completed': len(records), 'total': 2, 'records': records,
                'financial_validation_started': False, 'production_write': False})
            print('WICK_GEOMETRY_CONTRACT', len(records), '/', 2, descriptor['hypothesis'], match[2], flush=True)
        atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'manifest_sha256': sha(output / 'manifest.json'),
            'completed': 2, 'geometry_tests': 9, 'mechanism_groups': 1,
            'financial_validation_started': False, 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
