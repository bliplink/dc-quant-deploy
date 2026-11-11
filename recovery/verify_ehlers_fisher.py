"""Training engineering only: recursive median Fisher,64 independent convolution fixtures, actual source parity/regressions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from recovery.export_ehlers_fisher_candidate import VARIANTS, export_candidate, source_file
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.run_directional_clock_parallel import extra_slot_resources
from recovery.run_directional_clock_batch import require_hashes
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'protocol', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items(): setattr(args, name, value.resolve())
    output = args.output_dir
    if output.exists(): raise ValueError('preserve every engineering attempt; fresh output required')
    native = source_file(args.indsvr_repo)
    names = ('StrategyResearchBatchCli.java', 'EhlersFisherStrategy.java', 'EhlersFisherCatalog.java', 'EhlersFisherTest.java',
        'RunsClusteringStrategy.java', 'RunsClusteringCatalog.java', 'RunsClusteringTest.java',
        'CusumDriftStrategy.java', 'CusumDriftCatalog.java', 'CusumDriftTest.java',
        'DirectionalClockStrategy.java', 'DirectionalClockCatalog.java', 'DirectionalClockTest.java',
        'TrueAdxRepairStrategy.java', 'TrueAdxRepairCatalog.java', 'WickGeometryRepairStrategy.java',
        'WickGeometryRepairCatalog.java', 'OhlcvProfileProxyStrategy.java', 'OhlcvProfileProxyCatalog.java')
    sources = [native.with_name(name) for name in names]
    training = json.loads((args.training_input_dir / 'READY.json').read_text(encoding='utf-8'))
    protocol = json.loads(args.protocol.read_text(encoding='utf-8')); bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    if (training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'
            or sha(bars) != training['files']['BTCUSDT']['bars_sha256']
            or protocol != json.loads(Path(__file__).with_name('strategy_research_ehlers_fisher_protocol_20261111.json').read_text(encoding='utf-8'))
            or protocol.get('source_cohort') != 'ehlers_fisher_v1'
            or protocol.get('mechanism_group') != 'ehlers_recursive_fisher_reversal'
            or protocol.get('minimum_forward_contribution') != '0.20'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'):
        raise ValueError('unchanged training inputs and predeclared fixed recursive Fisher policy required')
    reference = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    original_cli = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    test_root = native.parent
    tests = sorted(test_root.glob('TrueAdxRepair*Test.java')) + sorted(test_root.glob('WickGeometryRepair*Test.java'))
    if len(tests) != 4: raise ValueError('all four preserved ADX/wick test sources required')
    tests += [test_root / 'OhlcvProfileProxyTest.java']
    extra = tests + [test_root / 'TrueAdxRepairSignalParityCli.java', test_root / 'WickGeometryRepairSignalParityCli.java']
    ref_root = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    reference_tests = sorted(p for p in ref_root.glob('*Test.class') if '$' not in p.name)
    if not reference_tests: raise ValueError('original complete regression test bytecode required')
    critical = {str(p): sha(p) for p in sources + extra + reference_tests + [reference, original_cli, args.protocol]}
    critical.update({str(p): sha(p) for p in Path(__file__).parent.glob('*.py')})
    critical[str(args.training_input_dir / 'READY.json')] = sha(args.training_input_dir / 'READY.json')
    critical[str(bars)] = sha(bars)
    runtime = {str(p): sha(p) for directory in ('dependency', 'javalib')
        for p in sorted((args.sim_repo / 'target' / directory).glob('*.jar'))}
    class_roots = [repo / 'target' / suffix for repo in (args.reference_indsvr_repo, args.sim_repo)
        for suffix in ('test-classes', 'classes')]
    reference_classes = {str(p): sha(p) for root in class_roots for p in sorted(root.rglob('*.class'))}
    if not runtime or not reference_classes: raise ValueError('complete actual reference classpath required')
    critical.update(runtime); critical.update(reference_classes)
    tools = {command: str(Path(shutil.which(command)).resolve()) for command in ('java', 'javac', 'jar')}
    critical.update({path: sha(Path(path)) for path in tools.values()})
    options = {key: hashlib.sha256(os.environ.get(key, '').encode()).hexdigest()
        for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')}
    junit = Path.home() / '.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'
    hamcrest = Path.home() / '.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar'
    critical[str(junit)] = sha(junit); critical[str(hamcrest)] = sha(hamcrest)
    output.mkdir(parents=True)
    with exclusive_batch(output):
        manifest = dict(schema='ehlers_fisher_engineering_v1', source_sha256={p.name: sha(p) for p in sources},
            source_validator_class_sha256=sha(reference), original_parity_cli_sha256=sha(original_cli),
            training_ready_sha256=sha(args.training_input_dir / 'READY.json'), training_bars_sha256=sha(bars),
            protocol_sha256=sha(args.protocol), exporter_sha256=sha(Path(__file__).with_name('export_ehlers_fisher_candidate.py')),
            wrapper_sha256=sha(Path(__file__)), critical_sha256=critical,
            runtime_jar_sha256=runtime, reference_class_sha256=reference_classes,
            java_executables=tools, java_option_environment_sha256=options,
            training_begin='2023-01-01', training_end='2023-12-31', mechanism_group='ehlers_recursive_fisher_reversal',
            variants=list(VARIANTS), financial_validation_started=False, forward_pnl_read=False, production_write=False)
        write_status(output / 'manifest.json', manifest); digest = sha(output / 'manifest.json'); records = []

        def guard(stage):
            resources = extra_slot_resources(output, 3072)
            while not resources['ready']:
                write_status(output / 'status.json', dict(state='WAITING_FOR_ENGINEERING_RESOURCES', stage=stage,
                    completed=len(records), total=2, resources=resources, financial_validation_started=False, production_write=False))
                time.sleep(10); resources = extra_slot_resources(output, 3072)
            require_hashes(critical)
            current_jars = {str(p) for directory in ('dependency', 'javalib')
                for p in (args.sim_repo / 'target' / directory).glob('*.jar')}
            current_classes = {str(p) for root in class_roots for p in root.rglob('*.class')}
            current_tools = {command: str(Path(shutil.which(command)).resolve()) for command in tools}
            current_options = {key: hashlib.sha256(os.environ.get(key, '').encode()).hexdigest() for key in options}
            if (current_jars != set(runtime) or current_classes != set(reference_classes)
                    or current_tools != tools or current_options != options):
                raise ValueError('actual frozen runtime membership/Java selection/options changed')
            write_status(output / 'status.json', dict(state='RUNNING_ENGINEERING', stage=stage,
                completed=len(records), total=2, financial_validation_started=False, production_write=False))

        classes = output / 'classes'; classes.mkdir()
        cp = os.pathsep.join([str(classes), str(args.reference_indsvr_repo / 'target/test-classes'),
            str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo),
            str(junit), str(hamcrest)])
        try:
            guard('mathematics-compile')
            execute(['javac', '-J-Xmx768m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(classes)] + list(map(str, sources)), output / 'compile.log')
            guard('mathematics-tests')
            text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp, 'org.junit.runner.JUnitCore',
                'com.app.dc.service.strategy.research.EhlersFisherTest'], output / 'mathematics-tests.log', args.indsvr_repo)
            if 'OK (15 tests)' not in text: raise ValueError('all15 recurrence/convolution/64 raw-OHLC fixture tests required')
            for side in VARIANTS:
                guard('source-compile:' + str(side))
                frozen, item, descriptor = export_candidate(args.indsvr_repo, output / 'frozen', 'BTCUSDT', 'trend', side)
                source = frozen / 'GeneratedStrategy.java'; name = item['strategyName']
                artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), args.sim_repo, output / 'artifacts' / name)
                guard('source-validator:' + str(side))
                execute(['java', '-Xmx256m', '-cp', cp,
                    'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source', str(source),
                    item['request']['logicSummary'], name], output / 'logs' / (name + '-source.log'))
                guard('full-year-training:' + str(side))
                text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
                    'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', str(bars), 'BTCUSDT',
                    '2023-01-01', '2023-12-31', descriptor['hypothesis'], str(artifact), entry], output / 'logs' / (name + '-parity.log'))
                found = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
                if not found or int(found[1]) != 35040 or found[2] != found[3] or int(found[4]) != 0 or int(found[2]) <= 0:
                    raise ValueError('actual nonzero35040-bar signal/risk/exit source parity required')
                records.append(dict(descriptor, strategy=name, source_sha256=sha(source), artifact_sha256=sha(artifact),
                    artifact_path=str(artifact), entry_class=entry, bars=int(found[1]), signals=int(found[2]), mismatches=0))
                write_status(output / 'status.json', dict(state='RUNNING_ENGINEERING', completed=len(records), total=2,
                    financial_validation_started=False, production_write=False))
                print('EHLERS_FISHER_SOURCE_PARITY', len(records), '/', 2, descriptor['hypothesis'], found[2], flush=True)
            test_names = sorted(set('com.app.dc.service.strategy.research.' + p.stem for p in reference_tests + tests)
                | {'com.app.dc.service.strategy.research.DirectionalClockTest', 'com.app.dc.service.strategy.research.CusumDriftTest',
                   'com.app.dc.service.strategy.research.EhlersFisherTest', 'com.app.dc.service.strategy.research.RunsClusteringTest'})
            write_status(output / 'regression-manifest.json', dict(engineering_manifest_sha256=digest,
                source_sha256={p.name: sha(p) for p in extra}, reference_test_sha256={p.name: sha(p) for p in reference_tests},
                tests=test_names, financial_validation_started=False, production_write=False))
            guard('full-regression-compile')
            execute(['javac', '-J-Xmx512m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(classes)] + list(map(str, extra)), output / 'regression-compile.log')
            guard('full-regression-tests')
            text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp, 'org.junit.runner.JUnitCore'] + test_names,
                output / 'full-research-regression.log', args.indsvr_repo)
            found = re.search(r'OK \((\d+) tests\)', text)
            if 'FAILURES' in text or not found or int(found[1]) < 187: raise ValueError('all preserved172 plus15 new tests required')
            require_hashes(critical)
            write_status(output / 'SOURCE_CONTRACT_COMPLETE.json', dict(manifest_sha256=digest, completed=2, mathematics_tests=15,
                independent_raw_ohlc_fixtures=64, independent_expanded_convolution_oracle=True, mechanism_groups=1,
                records=records, regression_tests=int(found[1]), regression_manifest_sha256=sha(output / 'regression-manifest.json'),
                regression_log_sha256=sha(output / 'full-research-regression.log'),
                class_sha256={str(p.relative_to(classes)): sha(p) for p in classes.rglob('*.class')},
                financial_validation_started=False, production_write=False))
            write_status(output / 'status.json', dict(state='COMPLETE', completed=2, total=2,
                financial_validation_started=False, production_write=False))
            print('EHLERS_FISHER_ENGINEERING_COMPLETE', found[1], 'regressions; no financial qualification', flush=True)
        except Exception as error:
            write_status(output / 'FAILED.json', dict(completed=len(records), error=str(error), production_write=False)); raise


if __name__ == '__main__': main()
