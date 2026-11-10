"""Engineering only: independent event oracle, original validator and full-year source parity."""

import argparse
import json
import os
from pathlib import Path
import re

from recovery.export_directional_clock_candidate import VARIANTS, export_candidate, source_file
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'protocol', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'reference_indsvr_repo', 'sim_repo', 'training_input_dir', 'protocol', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('preserve old attempts; a fresh engineering directory is required')
    native = source_file(args.indsvr_repo)
    names = ('StrategyResearchBatchCli.java', 'DirectionalClockStrategy.java', 'DirectionalClockCatalog.java',
             'DirectionalClockTest.java', 'TrueAdxRepairStrategy.java', 'TrueAdxRepairCatalog.java',
             'WickGeometryRepairStrategy.java', 'WickGeometryRepairCatalog.java',
             'OhlcvProfileProxyStrategy.java', 'OhlcvProfileProxyCatalog.java')
    sources = [native.with_name(name) for name in names]
    ready = json.loads((args.training_input_dir / 'READY.json').read_text(encoding='utf-8'))
    protocol = json.loads(args.protocol.read_text(encoding='utf-8'))
    bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(bars) != ready['files']['BTCUSDT']['bars_sha256']
            or protocol.get('source_cohort') != 'directional_clock_v1'
            or protocol.get('mechanism_group') != 'directional_change_overshoot_clock'):
        raise ValueError('unchanged pre-validation training and predeclared protocol required')
    reference = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    original_cli = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    output.mkdir(parents=True)
    manifest = {'schema': 'directional_clock_engineering_v1', 'source_sha256': {p.name: sha(p) for p in sources},
        'source_validator_class_sha256': sha(reference), 'original_parity_cli_sha256': sha(original_cli),
        'training_ready_sha256': sha(args.training_input_dir / 'READY.json'), 'training_bars_sha256': sha(bars),
        'protocol_sha256': sha(args.protocol), 'exporter_sha256': sha(Path(__file__).with_name('export_directional_clock_candidate.py')),
        'wrapper_sha256': sha(Path(__file__)), 'training_begin': '2023-01-01', 'training_end': '2023-12-31',
        'mechanism_group': 'directional_change_overshoot_clock', 'variants': list(VARIANTS),
        'financial_validation_started': False, 'forward_pnl_read': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    classes = output / 'classes'; classes.mkdir()
    cp = os.pathsep.join([str(classes), str(args.reference_indsvr_repo / 'target/test-classes'),
        str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo),
        str(Path.home() / '.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'),
        str(Path.home() / '.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar')])
    records = []
    try:
        execute(['javac', '-J-Xmx768m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
            '-d', str(classes)] + list(map(str, sources)), output / 'compile.log')
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp, 'org.junit.runner.JUnitCore',
            'com.app.dc.service.strategy.research.DirectionalClockTest'], output / 'mathematics-tests.log', args.indsvr_repo)
        if 'OK (16 tests)' not in text:
            raise ValueError('all sixteen event/64-independent-path/risk/causality tests required')
        for side in VARIANTS:
            frozen, item, descriptor = export_candidate(args.indsvr_repo, output / 'frozen', 'BTCUSDT', 'trend', side)
            source = frozen / 'GeneratedStrategy.java'; name = item['strategyName']
            artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifacts' / name)
            execute(['java', '-Xmx256m', '-cp', cp,
                'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source', str(source),
                item['request']['logicSummary'], name], output / 'logs' / (name + '-source.log'))
            text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
                'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', str(bars), 'BTCUSDT',
                '2023-01-01', '2023-12-31', descriptor['hypothesis'], str(artifact), entry],
                output / 'logs' / (name + '-parity.log'))
            match = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
            if (not match or int(match[1]) != 35040 or match[2] != match[3] or int(match[4]) != 0
                    or int(match[2]) <= 0):
                raise ValueError('full-year nonzero actual compiled-source signal parity required')
            records.append(dict(descriptor, strategy=name, source_sha256=sha(source), artifact_sha256=sha(artifact),
                artifact_path=str(artifact), entry_class=entry, bars=int(match[1]), signals=int(match[2]), mismatches=0))
            atomic_write_json(output / 'status.json', {'completed': len(records), 'total': 2, 'records': records,
                'financial_validation_started': False, 'production_write': False})
            print('DIRECTIONAL_CLOCK_CONTRACT', len(records), '/', 2, descriptor['hypothesis'], match[2], flush=True)
        atomic_write_json(output / 'SOURCE_CONTRACT_COMPLETE.json', {'manifest_sha256': sha(output / 'manifest.json'),
            'completed': 2, 'mathematics_tests': 16, 'independent_path_fixtures': 64, 'mechanism_groups': 1,
            'class_sha256': {str(p.relative_to(classes)): sha(p) for p in classes.rglob('*.class')},
            'financial_validation_started': False, 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
