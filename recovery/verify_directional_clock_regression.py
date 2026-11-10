"""Run every preserved research test against the new isolated event-clock catalog."""
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
        raise ValueError('preserve all regression attempts; fresh output required')
    complete = json.loads((args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json').read_text())
    if (complete.get('completed') != 2 or complete.get('mathematics_tests') != 16
            or complete.get('independent_path_fixtures') != 64
            or complete.get('manifest_sha256') != sha(args.engineering_dir / 'manifest.json')
            or complete.get('financial_validation_started') is not False):
        raise ValueError('complete two-source nonzero engineering proof required')
    for relative, expected in complete['class_sha256'].items():
        if sha(args.engineering_dir / 'classes' / relative) != expected:
            raise ValueError('engineering classes changed')
    source_root = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research'
    # Discover exact established filenames instead of inventing older test names.
    tests = sorted(source_root.glob('TrueAdxRepair*Test.java')) + sorted(source_root.glob('WickGeometryRepair*Test.java'))
    if len(tests) != 4:
        raise ValueError('four preserved ADX/wick test sources required')
    tests += [source_root / 'OhlcvProfileProxyTest.java']
    sources = tests + [source_root / 'TrueAdxRepairSignalParityCli.java', source_root / 'WickGeometryRepairSignalParityCli.java']
    reference_root = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    reference = sorted(p for p in reference_root.glob('*Test.class') if '$' not in p.name)
    if not reference:
        raise ValueError('original research test bytecode missing')
    test_names = sorted(set('com.app.dc.service.strategy.research.' + p.stem for p in reference + tests)
                        | {'com.app.dc.service.strategy.research.DirectionalClockTest'})
    output = args.output_dir; output.mkdir(parents=True)
    atomic_write_json(output / 'manifest.json', {'engineering_manifest_sha256': sha(args.engineering_dir / 'manifest.json'),
        'source_sha256': {p.name: sha(p) for p in sources}, 'reference_test_sha256': {p.name: sha(p) for p in reference},
        'tests': test_names, 'financial_validation_started': False, 'production_write': False})
    classes = output / 'classes'; classes.mkdir()
    cp = os.pathsep.join([str(classes), str(args.engineering_dir / 'classes'),
        str(args.reference_indsvr_repo / 'target/test-classes'), str(args.reference_indsvr_repo / 'target/classes'),
        java_classpath(args.sim_repo), str(Path.home() / '.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'),
        str(Path.home() / '.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar')])
    try:
        execute(['javac', '-J-Xmx512m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
            '-d', str(classes)] + list(map(str, sources)), output / 'compile.log')
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
            'org.junit.runner.JUnitCore'] + test_names, output / 'full-research-regression.log', args.indsvr_repo)
        if 'FAILURES' in text or 'OK (' not in text:
            raise ValueError('complete regression did not pass')
        atomic_write_json(output / 'audit.json', {'state': 'complete', 'manifest_sha256': sha(output / 'manifest.json'),
            'regression_log_sha256': sha(output / 'full-research-regression.log'), 'production_write': False})
        print(text, flush=True)
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'error': str(error), 'production_write': False}); raise


if __name__ == '__main__': main()
