"""Training only:20 actual full-year references and100 exact source/full-class identity proofs; never changes finance."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from recovery.class_identity_equivalence import require_jar_identity_equivalence, require_source_identity_equivalence
from recovery.export_cusum_drift_candidate import export_candidate, source_file
from recovery.local_strategy_backtest import compile_source, java_classpath
from recovery.run_cusum_drift_batch import frozen_queue, SCOPE_FIELDS
from recovery.run_directional_clock_batch import require_hashes
from recovery.run_directional_clock_parallel import extra_slot_resources
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.run_true_adx_batch import read
from recovery.verify_cusum_identity_parity import adapter_bindings
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute

SCENES = ('trend', 'range', 'channel', 'breakout', 'reversal')
ENGINEERING_SHA = '1aee7da502d093ab773a0c6b48ace9d127969b7c0a631219dcddb5a8ecfafb2b'


def training_symbols(ready):
    # This established training READY schema declares membership in files,
    # unlike the separately protocol-bound financial READY's symbols list.
    expected = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT'}
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or not isinstance(ready.get('files'), dict) or set(ready['files']) != expected):
        raise ValueError('original training READY files map with exactly ten symbols required')
    return sorted(ready['files'])


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def group_scopes(queue):
    if len(queue) != 100 or len({r['strategy'] for r in queue}) != 100 or len({r['symbol'] for r in queue}) != 10:
        raise ValueError('entire unique100-scope ten-symbol matrix required')
    groups = {}
    for row in queue:
        if (type(row['side']) is not int or row['side'] not in (1, -1) or row['scene'] not in SCENES
                or row['mechanism_group'] != 'standardized_return_cusum_drift'
                or row['family'] != 'CatalogAtrExitCusumDriftHypothesis'):
            raise ValueError('only the original CUSUM source policy may use this matrix')
        groups.setdefault((row['symbol'], row['side']), []).append(row)
    if len(groups) != 20 or any(Counter(r['scene'] for r in rows) != Counter(SCENES) for rows in groups.values()):
        raise ValueError('each of20 symbol/direction groups requires all five scenes exactly once')
    return [(key, sorted(rows, key=lambda r: SCENES.index(r['scene'])))
            for key, rows in sorted(groups.items(), key=lambda item: (item[0][0], -item[0][1]))]


def parse_parity(text):
    found = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
    if not found or int(found[1]) != 35040 or found[2] != found[3] or int(found[4]) != 0:
        raise ValueError('actual original35040-bar full-year signal/risk/exit parity required')
    return int(found[2])


def require_matching_reference(row, canonical):
    if (any(row[k] != canonical[k] for k in ('symbol', 'side', 'hypothesis', 'family', 'mechanism_group'))
            or canonical.get('scene') != 'trend' or canonical.get('training_bars') != 35040
            or canonical.get('mismatches') != 0 or canonical.get('actual_full_year_replay') is not True):
        raise ValueError('never reuse another symbol/direction/policy or an incomplete reference')


def verify_compiled_record(record):
    for path_key, digest_key in (('source_path', 'source_sha256'), ('artifact_path', 'artifact_sha256'),
            ('seed_path', 'seed_sha256'), ('validator_log_path', 'validator_log_sha256')):
        if sha(Path(record[path_key])) != record[digest_key]: raise ValueError('compiled source/seed/JAR/validator evidence changed')
    item = read(Path(record['seed_path']))['strategies'][0]
    if (any(item[k] != record[k] for k in ('symbol', 'scene')) or item['strategyName'] != record['strategy']
            or digest_json(item['request']['optimizationProfile']) != record['optimization_profile_sha256']
            or item['request']['parameterSchema'] != {} or item['request']['defaultParameters'] != {}):
        raise ValueError('scene-specific seed/parameter policy changed')


def classpath_classes(args):
    roots = (args.engineering_dir / 'classes', args.reference_indsvr_repo / 'target/test-classes',
        args.reference_indsvr_repo / 'target/classes', args.sim_repo / 'target/test-classes', args.sim_repo / 'target/classes')
    return {str(p): sha(p) for root in roots for p in sorted(root.rglob('*.class'))}


def require_matrix_coverage(queue, canonicals, records, context_sha):
    group_scopes(queue)
    if len(canonicals) != 20 or len(records) != 100 or len({r['strategy'] for r in records}) != 100:
        raise ValueError('all20 real references and100 exact source proofs required')
    by_name = {r['strategy']: r for r in records}
    references = {(r['symbol'], r['side']): r for r in canonicals}
    if (len(references) != 20 or set(references) != {(r['symbol'], r['side']) for r in queue}
            or set(by_name) != {r['strategy'] for r in queue}):
        raise ValueError('matrix scope/reference identities changed')
    for expected in queue:
        record = by_name[expected['strategy']]; canonical = references[(expected['symbol'], expected['side'])]
        if any(record[k] != expected[k] for k in SCOPE_FIELDS): raise ValueError('source scope descriptor changed')
        require_matching_reference(record, canonical)
        if (record.get('context_sha256') != context_sha or record.get('canonical_strategy') != canonical['strategy']
                or record.get('training_bars') != 35040 or record.get('mismatches') != 0
                or record.get('training_signals') != canonical['training_signals']
                or record.get('canonical_full_year_log_sha256') != canonical['full_year_log_sha256']):
            raise ValueError('source proof is not bound to its exact full-year reference/context')


def frozen_context(args):
    engineering = read(args.engineering_dir / 'manifest.json'); complete = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json')
    if (sha(args.engineering_dir / 'manifest.json') != ENGINEERING_SHA or complete.get('manifest_sha256') != ENGINEERING_SHA
            or sha(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json') != '82f5a94843b1dc570a0fc23e208303dd7cb483f90044692a0d22ba0498958525'
            or complete.get('completed') != 2 or complete.get('mathematics_tests') != 16
            or complete.get('independent_suffix_fixtures') != 64 or complete.get('regression_tests') != 155
            or complete.get('financial_validation_started') is not False):
        raise ValueError('exact original16/64/two-source/155-Java CUSUM proof required')
    pilot, pilot_manifest = read(args.pilot_dir / 'audit.json'), read(args.pilot_dir / 'manifest.json')
    marker = read(args.pilot_dir / 'PILOT_COMPLETE.json')
    if (marker.get('audit_sha256') != sha(args.pilot_dir / 'audit.json')
            or sha(args.pilot_dir / 'audit.json') != '7744250d17ab1c63064cf89b3bccc59efdfb3ec82883dbf52d6768e2b9de217c'
            or sha(args.pilot_dir / 'manifest.json') != '21d831ce9bdbf36a3fc9bb2781e2d0c19281ffbba59c0065d21138219d5b6687'
            or pilot.get('manifest_sha256') != sha(args.pilot_dir / 'manifest.json')
            or marker.get('manifest_sha256') != pilot['manifest_sha256']
            or pilot.get('training_bars') != 35040 or pilot.get('signals') != 535 or pilot.get('mismatches') != 0
            or pilot.get('runtime_reuse_enabled') is not False or len(pilot.get('negative_controls', [])) != 2
            or any(not r.get('source_rejected') or not r.get('bytecode_rejected') for r in pilot['negative_controls'])):
        raise ValueError('original actual positive and compiled negative-control pilot required')
    require_hashes(pilot_manifest['frozen_input_and_tool_sha256'])
    helper = Path(__file__).with_name('class_identity_equivalence.py')
    if [h for n, h in pilot_manifest['tool_sha256'].items() if Path(n).name == helper.name] != [sha(helper)]:
        raise ValueError('matrix must use the exact actual-pilot class-file normalizer')
    native = source_file(args.indsvr_repo)
    critical = {str(native.with_name(n)): h for n, h in engineering['source_sha256'].items()}
    critical.update({str(args.engineering_dir / 'classes' / n): h for n, h in complete['class_sha256'].items()})
    reference = args.reference_indsvr_repo
    validator = reference / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    cli = reference / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    critical[str(validator)] = engineering['source_validator_class_sha256']; critical[str(cli)] = engineering['original_parity_cli_sha256']
    for filename in ('manifest.json', 'SOURCE_CONTRACT_COMPLETE.json', 'regression-manifest.json', 'full-research-regression.log'):
        critical[str(args.engineering_dir / filename)] = sha(args.engineering_dir / filename)
    if (sha(args.engineering_dir / 'regression-manifest.json') != complete['regression_manifest_sha256']
            or sha(args.engineering_dir / 'full-research-regression.log') != complete['regression_log_sha256']):
        raise ValueError('original complete regression evidence changed')
    tools = {str(p): sha(p) for p in Path(__file__).parent.glob('*.py')}; critical.update(tools)
    if engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_cusum_drift_candidate.py')):
        raise ValueError('original fixed source factory changed')
    ready = read(args.training_input_dir / 'READY.json')
    symbols = training_symbols(ready)
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(args.training_input_dir / 'READY.json') != engineering['training_ready_sha256']):
        raise ValueError('untouched pre-validation training data required')
    data = {str(args.training_input_dir / 'READY.json'): sha(args.training_input_dir / 'READY.json')}
    for symbol in symbols: data[str(args.training_input_dir / (symbol + '-15m.tsv'))] = ready['files'][symbol]['bars_sha256']
    jars = {str(p): sha(p) for directory in ('dependency', 'javalib') for p in sorted((args.sim_repo / 'target' / directory).glob('*.jar'))}
    if not jars: raise ValueError('real original Java runtime artifacts required')
    for command in ('java', 'javac', 'jar'):
        path = shutil.which(command)
        if not path: raise ValueError('missing original Java tool: ' + command)
        critical[str(Path(path).resolve())] = sha(Path(path).resolve())
    adapters = adapter_bindings(args)
    if adapters != pilot_manifest['adapter_bindings']: raise ValueError('actual adapter classpath changed since pilot')
    require_hashes(critical); require_hashes(data); require_hashes(jars)
    return dict(critical_sha256=critical, training_sha256=data, runtime_jar_sha256=jars,
        classpath_class_sha256=classpath_classes(args),
        adapter_bindings=adapters, engineering_manifest_sha256=ENGINEERING_SHA,
        pilot_audit_sha256=sha(args.pilot_dir / 'audit.json'),
        java_option_environment_sha256={key: hashlib.sha256(os.environ.get(key, '').encode()).hexdigest()
            for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')}), symbols


class MatrixRunner:
    def __init__(self, args, context, manifest_sha):
        self.args, self.context, self.manifest_sha = args, context, manifest_sha
        self.context_sha = digest_json(context); self.canonicals = []; self.records = []
        self.cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
            str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])

    def status(self, state, **extra):
        write_status(self.args.output_dir / 'status.json', dict(state=state, completed_groups=len(self.canonicals), total_groups=20,
            completed_scopes=len(self.records), total_scopes=100, financial_validation_started=False, runtime_reuse_enabled=False,
            production_write=False, **extra))

    def guard(self, stage):
        resources = extra_slot_resources(self.args.output_dir, 3072)
        while not resources['ready']:
            self.status('WAITING_FOR_MATRIX_RESOURCES', stage=stage, resources=resources)
            time.sleep(10); resources = extra_slot_resources(self.args.output_dir, 3072)
        require_hashes(self.context['critical_sha256'])
        self.status('RUNNING_TRAINING_MATRIX', stage=stage, resources=resources)

    def verify_environment(self):
        jars = {str(p) for directory in ('dependency', 'javalib')
            for p in (self.args.sim_repo / 'target' / directory).glob('*.jar')}
        if jars != set(self.context['runtime_jar_sha256']) or classpath_classes(self.args) != self.context['classpath_class_sha256']:
            raise ValueError('original complete runtime classpath membership/bytecode changed')
        require_hashes(self.context['runtime_jar_sha256']); require_hashes(self.context['training_sha256'])

    def compile_and_validate(self, row):
        self.guard('compile:' + row['strategy'])
        frozen, item, _ = export_candidate(self.args.indsvr_repo, self.args.output_dir / 'frozen', row['symbol'], row['scene'], row['side'])
        source = frozen / 'GeneratedStrategy.java'
        artifact, entry, _ = compile_source(source.read_text(encoding='utf-8'), self.args.sim_repo,
            self.args.output_dir / 'artifacts' / row['strategy'])
        log = self.args.output_dir / 'logs' / (row['strategy'] + '-validator.log')
        self.guard('source-validator:' + row['strategy'])
        execute(['java', '-Xmx256m', '-cp', self.cp, 'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
            '--validate-source', str(source), item['request']['logicSummary'], row['strategy']], log)
        return dict(row, source_path=str(source), source_sha256=sha(source), artifact_path=str(artifact), artifact_sha256=sha(artifact),
            entry_class=entry, seed_path=str(frozen / 'seed.json'), seed_sha256=sha(frozen / 'seed.json'),
            optimization_profile_sha256=digest_json(item['request']['optimizationProfile']),
            validator_log_path=str(log), validator_log_sha256=sha(log), context_sha256=self.context_sha)

    def group(self, rows):
        self.verify_environment()
        reference = self.compile_and_validate(rows[0])
        log = self.args.output_dir / 'logs' / (reference['strategy'] + '-full-year-parity.log')
        self.guard('full-year-reference:' + reference['strategy'])
        start = time.monotonic()
        text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', self.cp,
            'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
            str(self.args.training_input_dir / (reference['symbol'] + '-15m.tsv')), reference['symbol'], '2023-01-01', '2023-12-31',
            reference['hypothesis'], reference['artifact_path'], reference['entry_class']], log)
        reference.update(training_bars=35040, training_signals=parse_parity(text), mismatches=0,
            full_year_log_path=str(log), full_year_log_sha256=sha(log), actual_full_year_replay=True,
            replay_seconds=time.monotonic() - start)
        group_root = self.args.output_dir / 'groups' / reference['symbol'] / ('long' if reference['side'] > 0 else 'short')
        group_root.mkdir(parents=True)
        write_status(group_root / 'canonical.json', reference)
        records = []
        for row in rows:
            current = reference.copy() if row['strategy'] == reference['strategy'] else self.compile_and_validate(row)
            require_matching_reference(current, reference)
            require_source_identity_equivalence(Path(reference['source_path']).read_text(encoding='utf-8'), reference['strategy'],
                Path(current['source_path']).read_text(encoding='utf-8'), current['strategy'])
            identity = require_jar_identity_equivalence(Path(reference['artifact_path']), reference['strategy'],
                Path(current['artifact_path']), current['strategy'])
            if len(identity['normalized_class_sha256']) != 3: raise ValueError('all three original generated classes required')
            current.update(canonical_strategy=reference['strategy'], canonical_source_sha256=reference['source_sha256'],
                canonical_artifact_sha256=reference['artifact_sha256'], canonical_full_year_log_sha256=reference['full_year_log_sha256'],
                training_bars=35040, training_signals=reference['training_signals'], mismatches=0, identity_proof=identity,
                training_evidence_mode='actual_canonical_full_year_and_exact_source_full_class_identity',
                runtime_reuse_enabled=False, financial_validation_started=False, production_write=False)
            write_status(group_root / (row['strategy'] + '.json'), current); records.append(current)
        for current in records: verify_compiled_record(current)
        self.verify_environment()
        write_status(group_root / 'GROUP_COMPLETE.json', dict(matrix_manifest_sha256=self.manifest_sha, context_sha256=self.context_sha,
            canonical_sha256=sha(group_root / 'canonical.json'),
            scope_proof_sha256={r['strategy']: sha(group_root / (r['strategy'] + '.json')) for r in records},
            completed_scopes=5, actual_full_year_replays=1, runtime_reuse_enabled=False, production_write=False))
        self.canonicals.append(reference); self.records.extend(records)
        self.status('RUNNING_TRAINING_MATRIX')
        print('CUSUM_IDENTITY_MATRIX_GROUP', len(self.canonicals), '/', 20, reference['symbol'], reference['side'],
            'signals', reference['training_signals'], 'scope_proofs', len(self.records), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'engineering-dir', 'pilot-dir', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items(): setattr(args, name, value.resolve())
    if args.output_dir.exists(): raise ValueError('preserve every matrix attempt; fresh output required')
    context, symbols = frozen_context(args)
    queue = frozen_queue(source_file(args.indsvr_repo).read_text(encoding='utf-8'), symbols)
    groups = group_scopes(queue); args.output_dir.mkdir(parents=True)
    with exclusive_batch(args.output_dir):
        manifest = dict(schema='cusum_complete_training_identity_matrix_v1', queue=queue, context=context,
            canonical_groups=20, scope_proofs=100, mechanism_groups=1, runtime_reuse_enabled=False,
            financial_validation_started=False, new_holdout_read=False, production_write=False)
        write_status(args.output_dir / 'manifest.json', manifest); digest = sha(args.output_dir / 'manifest.json')
        runner = MatrixRunner(args, context, digest)
        try:
            for _, rows in groups: runner.group(rows)
            require_matrix_coverage(queue, runner.canonicals, runner.records, runner.context_sha)
            references = {(r['symbol'], r['side']): r for r in runner.canonicals}
            for record in runner.records:
                verify_compiled_record(record); canonical = references[(record['symbol'], record['side'])]
                if sha(Path(canonical['full_year_log_path'])) != canonical['full_year_log_sha256']:
                    raise ValueError('actual original full-year log changed')
                if parse_parity(Path(canonical['full_year_log_path']).read_text(encoding='utf-8')) != canonical['training_signals']:
                    raise ValueError('actual full-year signal evidence changed')
                require_source_identity_equivalence(Path(canonical['source_path']).read_text(encoding='utf-8'), canonical['strategy'],
                    Path(record['source_path']).read_text(encoding='utf-8'), record['strategy'])
                if require_jar_identity_equivalence(Path(canonical['artifact_path']), canonical['strategy'],
                        Path(record['artifact_path']), record['strategy']) != record['identity_proof']:
                    raise ValueError('final complete class-file proof changed')
            runner.verify_environment()
            require_hashes(context['critical_sha256']); require_hashes(context['runtime_jar_sha256']); require_hashes(context['training_sha256'])
            write_status(args.output_dir / 'matrix.json', dict(manifest_sha256=digest, context_sha256=runner.context_sha,
                canonical_references=runner.canonicals, scope_records=runner.records,
                actual_full_year_replays=20, actual_source_validations=100, actual_scope_compilations=100,
                runtime_reuse_enabled=False, runtime_admission_ready=False, financial_validation_started=False,
                new_holdout_read=False, production_write=False))
            write_status(args.output_dir / 'MATRIX_COMPLETE.json', dict(manifest_sha256=digest,
                matrix_sha256=sha(args.output_dir / 'matrix.json'), completed_groups=20, completed_scopes=100,
                nonzero_reference_groups=sum(r['training_signals'] > 0 for r in runner.canonicals),
                runtime_reuse_enabled=False, runtime_admission_ready=False, production_write=False))
            runner.status('COMPLETE')
        except Exception as error:
            write_status(args.output_dir / 'FAILED.json', dict(error=str(error), completed_groups=len(runner.canonicals),
                completed_scopes=len(runner.records), financial_validation_started=False, production_write=False)); raise


if __name__ == '__main__': main()
