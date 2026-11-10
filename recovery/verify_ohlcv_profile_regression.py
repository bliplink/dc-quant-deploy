"""Run the unchanged research regression suite against the isolated new catalog/classes."""

import argparse
import json
import os
from pathlib import Path

from recovery.local_strategy_backtest import java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'engineering-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'reference_indsvr_repo', 'sim_repo', 'engineering_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.output_dir.exists():
        raise ValueError('preserve old regression attempts; fresh output required')
    complete = json.loads((args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json').read_text(encoding='utf-8'))
    if (complete.get('completed') != 4 or complete.get('mathematics_tests') != 12
            or complete.get('manifest_sha256') != sha(args.engineering_dir / 'manifest.json')
            or complete.get('financial_validation_started') is not False):
        raise ValueError('complete unchanged four-source engineering proof required')
    for relative, expected in complete['class_sha256'].items():
        if sha(args.engineering_dir / 'classes' / relative) != expected:
            raise ValueError('frozen engineering bytecode changed')
    source_root = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research'
    sources = sorted(source_root.glob('TrueAdxRepair*Test.java')) + sorted(source_root.glob('WickGeometryRepair*Test.java'))
    if len(sources) != 4:
        raise ValueError('four preserved ADX/wick tests required')
    all_sources = sources + [source_root / 'TrueAdxRepairSignalParityCli.java',
                             source_root / 'WickGeometryRepairSignalParityCli.java']
    reference_root = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    reference = sorted(path for path in reference_root.glob('*Test.class') if '$' not in path.name)
    if not reference:
        raise ValueError('original research regression classes required')
    tests = sorted(set('com.app.dc.service.strategy.research.' + path.stem for path in reference + sources)
                   | {'com.app.dc.service.strategy.research.OhlcvProfileProxyTest'})
    output = args.output_dir
    output.mkdir(parents=True)
    manifest = {'engineering_manifest_sha256': sha(args.engineering_dir / 'manifest.json'),
        'source_sha256': {path.name: sha(path) for path in all_sources},
        'reference_test_sha256': {path.name: sha(path) for path in reference}, 'tests': tests,
        'financial_validation_started': False, 'production_write': False}
    atomic_write_json(output / 'manifest.json', manifest)
    classes = output / 'classes'
    classes.mkdir()
    cp = os.pathsep.join([str(classes), str(args.engineering_dir / 'classes'),
        str(args.reference_indsvr_repo / 'target/test-classes'), str(args.reference_indsvr_repo / 'target/classes'),
        java_classpath(args.sim_repo), str(Path.home() / '.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'),
        str(Path.home() / '.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar')])
    try:
        execute(['javac', '-J-Xmx512m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
            '-d', str(classes)] + list(map(str, all_sources)), output / 'compile.log')
        stdout = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
            'org.junit.runner.JUnitCore'] + tests, output / 'full-research-regression.log', args.indsvr_repo)
        if 'FAILURES' in stdout or 'OK (' not in stdout:
            raise ValueError('full research regression did not pass')
        atomic_write_json(output / 'audit.json', {'state': 'complete', 'manifest_sha256': sha(output / 'manifest.json'),
            'regression_log_sha256': sha(output / 'full-research-regression.log'), 'production_write': False})
        print(stdout, flush=True)
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'error': str(error), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
