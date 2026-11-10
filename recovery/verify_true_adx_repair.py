"""Compile fixed real-ADX sources, run reference tests and 2023 signal parity before finance."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from recovery.export_true_adx_candidate import export_candidate, source_file, VARIANTS
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha


def execute(command, log, cwd=None):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd, timeout=900)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('true ADX engineering failed; preserve ' + str(log))
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
        raise ValueError('each engineering attempt requires a fresh proof directory')
    sources = [source_file(args.indsvr_repo), source_file(args.indsvr_repo).with_name('TrueAdxRepairStrategyTest.java'),
               source_file(args.indsvr_repo).with_name('TrueAdxRepairSignalParityCli.java')]
    ready = json.loads((args.training_input_dir / 'READY.json').read_text(encoding='utf-8'))
    bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(bars) != ready['files']['BTCUSDT']['bars_sha256']):
        raise ValueError('untouched pre-validation training input required')
    jar = args.sim_repo / 'target/dependency/ta4j-core-0.15.jar'
    if not jar.is_file():
        raise ValueError('pinned actual ta4j 0.15 reference missing')
    output.mkdir(parents=True)
    manifest = {'schema': 'true_adx_repair_engineering_v1', 'source_sha256': {p.name: sha(p) for p in sources},
        'reference_ta4j_version': '0.15', 'reference_ta4j_jar_sha256': sha(jar),
        'source_validator_class_sha256': sha(args.reference_indsvr_repo /
            'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'),
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'training_bars_sha256': sha(bars),
        'exporter_sha256': sha(Path(__file__).with_name('export_true_adx_candidate.py')),
        'wrapper_sha256': sha(Path(__file__)), 'training_begin': '2023-01-01', 'training_end': '2023-12-31',
        'variants': list(VARIANTS), 'mechanism_group': 'wilder_adx_directional_breakout',
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
        tests = execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', cp, 'org.junit.runner.JUnitCore',
            'com.app.dc.service.strategy.research.TrueAdxRepairStrategyTest'], output / 'reference-tests.log', args.indsvr_repo)
        if 'OK (8 tests)' not in tests:
            raise ValueError('all eight actual-reference/causality/source tests required')
        for side, selective in VARIANTS:
            frozen, item, descriptor = export_candidate(args.indsvr_repo, output / 'frozen', 'BTCUSDT', 'trend', side, selective)
            source = frozen / 'GeneratedStrategy.java'
            name = item['strategyName']
            artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifacts' / name)
            execute(['java', '-Xmx256m', '-cp', cp,
                'com.app.dc.service.strategy.research.TrueAdxRepairSignalParityCli', '--validate-source', str(source),
                item['request']['logicSummary'], name], output / 'logs' / (name + '-source.log'))
            text = execute(['java', '-Xmx512m', '-Duser.timezone=UTC', '-cp', cp,
                'com.app.dc.service.strategy.research.TrueAdxRepairSignalParityCli', str(bars), 'BTCUSDT',
                '2023-01-01', '2023-12-31', str(artifact), entry, name, str(side), str(selective).lower()],
                output / 'logs' / (name + '-signal-parity.log'))
            match = re.search(r'TRUE_ADX_PARITY bars=(\d+) expectedSignals=(\d+) exportedSignals=(\d+) mismatches=(\d+)', text)
            if not match or int(match[1]) != 35040 or int(match[2]) <= 0 or match[2] != match[3] or int(match[4]) != 0:
                raise ValueError('nonzero full-training-year exact source/signal parity required')
            record = dict(descriptor, strategy=name, source_sha256=sha(source), artifact_sha256=sha(artifact),
                artifact_path=str(artifact), entry_class=entry, bars=int(match[1]), signals=int(match[2]), mismatches=0)
            records.append(record)
            atomic_write_json(output / 'status.json', {'completed': len(records), 'total': 4, 'records': records,
                'financial_validation_started': False, 'production_write': False})
            print('TRUE_ADX_CONTRACT', len(records), '/', 4, descriptor['hypothesis'], 'signals', match[2], flush=True)
        atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'manifest_sha256': sha(output / 'manifest.json'),
            'completed': len(records), 'actual_reference_tests': 8, 'financial_validation_started': False,
            'production_write': False, 'mechanism_groups_not_four_independent_strategies': 1})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
