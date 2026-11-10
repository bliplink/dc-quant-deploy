"""Training-only original-validator/full-year generated-source proof for the fixed OHLCV proxy."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from recovery.export_ohlcv_profile_proxy_candidate import VARIANTS, export_candidate, source_file
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha


def execute(command, log, cwd=None):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd, timeout=900)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('profile engineering failed; preserve ' + str(log))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'protocol', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'reference_indsvr_repo', 'sim_repo', 'training_input_dir', 'protocol', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('preserve every engineering attempt; fresh output required')
    native = source_file(args.indsvr_repo)
    names = ('StrategyResearchBatchCli.java', 'OhlcvProfileProxyStrategy.java', 'OhlcvProfileProxyCatalog.java',
             'OhlcvProfileProxyTest.java', 'TrueAdxRepairStrategy.java', 'TrueAdxRepairCatalog.java',
             'WickGeometryRepairStrategy.java', 'WickGeometryRepairCatalog.java')
    sources = [native.with_name(name) for name in names]
    ready = json.loads((args.training_input_dir / 'READY.json').read_text(encoding='utf-8'))
    protocol = json.loads(args.protocol.read_text(encoding='utf-8'))
    bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(bars) != ready['files']['BTCUSDT']['bars_sha256']
            or protocol.get('source_cohort') != 'ohlcv_profile_proxy_v1'
            or protocol.get('mechanism_group') != 'ohlcv_distribution_auction'):
        raise ValueError('untouched training-only market data and declared profile protocol required')
    reference = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    original_cli = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    output.mkdir(parents=True)
    manifest = {'schema': 'ohlcv_profile_proxy_engineering_v1', 'source_sha256': {path.name: sha(path) for path in sources},
        'source_validator_class_sha256': sha(reference), 'original_parity_cli_sha256': sha(original_cli),
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'training_bars_sha256': sha(bars),
        'protocol_sha256': sha(args.protocol), 'exporter_sha256': sha(Path(__file__).with_name('export_ohlcv_profile_proxy_candidate.py')),
        'wrapper_sha256': sha(Path(__file__)), 'training_begin': '2023-01-01', 'training_end': '2023-12-31',
        'mechanism_group': 'ohlcv_distribution_auction', 'variants': list(VARIANTS),
        'financial_validation_started': False, 'forward_pnl_read': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    classes = output / 'classes'
    classes.mkdir()
    cp = os.pathsep.join([str(classes), str(args.reference_indsvr_repo / 'target/test-classes'),
        str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo),
        str(Path.home() / '.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'),
        str(Path.home() / '.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar')])
    records = []
    try:
        execute(['javac', '-J-Xmx768m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
            '-d', str(classes)] + list(map(str, sources)), output / 'compile.log')
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp, 'org.junit.runner.JUnitCore',
            'com.app.dc.service.strategy.research.OhlcvProfileProxyTest'], output / 'mathematics-tests.log', args.indsvr_repo)
        if 'OK (12 tests)' not in text:
            raise ValueError('all twelve independent histogram/boundary/risk/causality/source tests required')
        for mode, side in VARIANTS:
            frozen, item, descriptor = export_candidate(args.indsvr_repo, output / 'frozen', 'BTCUSDT', 'trend', side, mode)
            source = frozen / 'GeneratedStrategy.java'
            name = item['strategyName']
            artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifacts' / name)
            execute(['java', '-Xmx256m', '-cp', cp,
                'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source', str(source),
                item['request']['logicSummary'], name], output / 'logs' / (name + '-source.log'))
            text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
                'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', str(bars), 'BTCUSDT',
                '2023-01-01', '2023-12-31', descriptor['hypothesis'], str(artifact), entry],
                output / 'logs' / (name + '-parity.log'))
            match = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
            if not match or int(match[1]) != 35040 or match[2] != match[3] or int(match[4]) != 0:
                raise ValueError('full-year original CLI source parity required')
            records.append(dict(descriptor, strategy=name, source_sha256=sha(source), artifact_sha256=sha(artifact),
                artifact_path=str(artifact), entry_class=entry, bars=int(match[1]), signals=int(match[2]),
                nonzero_signal_coverage=int(match[2]) > 0, mismatches=0))
            atomic_write_json(output / 'status.json', {'completed': len(records), 'total': 4, 'records': records,
                'financial_validation_started': False, 'production_write': False})
            print('OHLCV_PROFILE_CONTRACT', len(records), '/', 4, descriptor['hypothesis'], match[2], flush=True)
        atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'manifest_sha256': sha(output / 'manifest.json'),
            'completed': 4, 'mathematics_tests': 12, 'independent_histogram_fixtures': 64, 'mechanism_groups': 1,
            'class_sha256': {str(path.relative_to(classes)): sha(path) for path in classes.rglob('*.class')},
            'financial_validation_started': False, 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
