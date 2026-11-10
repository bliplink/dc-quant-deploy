"""100 fixed event-clock scopes; original formal/strict/disjoint holdout gates, no server path."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import time

import psutil

from recovery.export_directional_clock_candidate import VARIANTS, export_candidate, frozen_source, source_file
from recovery.local_strategy_backtest import java_classpath
from recovery.run_fit_risk_admission import require_proof
from recovery.run_fit_risk_catalog_batch import exclusive_batch, resource_state, write_status
from recovery.run_ohlcv_profile_proxy_batch import run_case
from recovery.run_true_adx_batch import completed_case, read
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute
from recovery.watch_fixed_primary_supplements import parent_alive

SCOPE_FIELDS = ('strategy', 'symbol', 'scene', 'hypothesis', 'family', 'mechanism_group', 'side')
DEPENDENCIES = ('run_ohlcv_profile_proxy_batch.py', 'run_true_adx_batch.py', 'run_fit_risk_catalog_batch.py',
                'verify_ohlcv_profile_proxy.py', 'strict_primary_admission.py', 'run_fit_risk_admission.py',
                'temporal_admission_contract.py', 'strategy_recovery_common.py', 'local_strategy_backtest.py',
                'watch_fixed_primary_supplements.py')


def frozen_queue(native, symbols):
    if len(symbols) != 10 or len(set(symbols)) != 10:
        raise ValueError('ten distinct original symbols required')
    rows = []
    for symbol in sorted(symbols):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            for side in VARIANTS:
                _, item, descriptor = frozen_source(native, symbol, scene, side)
                rows.append(dict(descriptor, strategy=item['strategyName'], symbol=symbol, scene=scene))
    if len(rows) != 100 or len({r['strategy'] for r in rows}) != 100:
        raise ValueError('exactly100 unique scopes, not100 independent mechanisms, required')
    return rows


def export_source(args, row):
    return export_candidate(args.indsvr_repo, args.output_dir / 'frozen', row['symbol'], row['scene'], row['side'])


def require_parent_complete(parent):
    folder = Path(parent['output_dir']); manifest = read(folder / 'manifest.json')
    complete, status = read(folder / 'FORMAL_COMPLETE.json'), read(folder / 'status.json')
    if (sha(folder / 'manifest.json') != parent['manifest_sha256']
            or complete.get('manifest_sha256') != parent['manifest_sha256']
            or complete.get('completed') != 200 or complete.get('production_write') is not False
            or status.get('completed') != 200 or status.get('total') != 200
            or len(manifest.get('queue', [])) != 200 or (folder / 'FAILED.json').exists()):
        raise ValueError('bound profile parent must genuinely complete200, not disappear/fail')
    for row in manifest['queue']:
        result = completed_case(folder / 'candidates' / row['strategy'], parent['manifest_sha256'])
        if any(result[k] != row[k] for k in SCOPE_FIELDS):
            raise ValueError('bound parent completed source identities changed')


def frozen_tool_paths(args, helpers):
    tool_root = Path(__file__).parent
    paths = [Path(__file__), tool_root / 'export_directional_clock_candidate.py', args.protocol]
    paths += [tool_root / n for n in DEPENDENCIES] + helpers
    return {str(p): sha(p) for p in paths}


def require_hashes(expected):
    for name, digest in expected.items():
        if sha(Path(name)) != digest:
            raise ValueError('frozen source/tool/protocol changed: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('indsvr-repo', 'reference-indsvr-repo', 'sim-repo', 'training-input-dir', 'input-dir', 'protocol',
             'engineering-dir', 'regression-dir', 'fit-oracle-dir', 'locked-oracle-dir', 'output-dir', 'wait-for-parent-dir')
    for name in names: parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--wait-for-parent-pid', type=int, required=True)
    args = parser.parse_args()
    for name in names:
        key = name.replace('-', '_'); setattr(args, key, getattr(args, key).resolve())
    java_dir = Path(__file__).with_name('java')
    require_proof(args.fit_oracle_dir, java_dir, args.sim_repo)
    locked, locked_manifest = read(args.locked_oracle_dir / 'audit.json'), read(args.locked_oracle_dir / 'manifest.json')
    if (locked.get('state') != 'complete' or locked.get('cases') != 12
            or locked['manifest_sha256'] != sha(args.locked_oracle_dir / 'manifest.json')
            or locked_manifest['java_source_sha256']['OfflineTemporalReplayCli.java'] != sha(java_dir / 'OfflineTemporalReplayCli.java')):
        raise ValueError('original twelve-case locked replay proof required')
    complete, engineering = read(args.engineering_dir / 'SOURCE_CONTRACT_COMPLETE.json'), read(args.engineering_dir / 'manifest.json')
    regression = read(args.regression_dir / 'audit.json')
    if (complete.get('completed') != 2 or complete.get('mathematics_tests') != 16 or complete.get('independent_path_fixtures') != 64
            or complete['manifest_sha256'] != sha(args.engineering_dir / 'manifest.json')
            or complete.get('financial_validation_started') is not False or complete.get('production_write') is not False
            or engineering['exporter_sha256'] != sha(Path(__file__).with_name('export_directional_clock_candidate.py'))
            or engineering['protocol_sha256'] != sha(args.protocol)
            or engineering['training_ready_sha256'] != sha(args.training_input_dir / 'READY.json')
            or regression.get('state') != 'complete' or regression['manifest_sha256'] != sha(args.regression_dir / 'manifest.json')
            or regression['regression_log_sha256'] != sha(args.regression_dir / 'full-research-regression.log')
            or read(args.regression_dir / 'manifest.json')['engineering_manifest_sha256'] != complete['manifest_sha256']):
        raise ValueError('complete engineering, independent oracle and regression proof required')
    native = source_file(args.indsvr_repo)
    source_hashes = {str(native.with_name(n)): d for n, d in engineering['source_sha256'].items()}
    class_hashes = {str(args.engineering_dir / 'classes' / n): d for n, d in complete['class_sha256'].items()}
    require_hashes(source_hashes); require_hashes(class_hashes)
    reference = args.reference_indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    original_cli = args.reference_indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research/RepresentativeSignalParityCli.class'
    if sha(reference) != engineering['source_validator_class_sha256'] or sha(original_cli) != engineering['original_parity_cli_sha256']:
        raise ValueError('original validator/parity bytecode changed')
    ready, protocol, training = read(args.input_dir / 'READY.json'), read(args.protocol), read(args.training_input_dir / 'READY.json')
    if (ready['protocol_sha256'] != sha(args.protocol) or protocol.get('source_cohort') != 'directional_clock_v1'
            or protocol.get('mechanism_group') != 'directional_change_overshoot_clock'
            or protocol.get('selection_mode') != 'fixed_source_no_parameter_grid'
            or training.get('purpose') != 'training_only' or training.get('train_end_exclusive') != '2024-12-15'):
        raise ValueError('unchanged fixed temporal protocol and training required')
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            if sha(args.input_dir / (symbol + suffix)) != ready['files'][symbol][key]: raise ValueError('market data changed')
        if sha(args.training_input_dir / (symbol + '-15m.tsv')) != training['files'][symbol]['bars_sha256']:
            raise ValueError('training data changed')
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    with exclusive_batch(output):
        if (output / 'FAILED.json').exists(): raise ValueError('preserve prior failure before diagnosis')
        previous = read(output / 'manifest.json') if (output / 'manifest.json').exists() else None
        parent = previous.get('parent_identity') if previous else None
        if parent is None:
            process = psutil.Process(args.wait_for_parent_pid); command = process.cmdline()
            if ('-m' not in command or '--output-dir' not in command
                    or command[command.index('-m') + 1] != 'recovery.run_ohlcv_profile_proxy_batch'
                    or Path(command[command.index('--output-dir') + 1]).resolve() != args.wait_for_parent_dir):
                raise ValueError('exact live OHLCV profile parent required before freezing')
            parent = {'pid': process.pid, 'create_time': process.create_time(), 'command': command,
                      'output_dir': str(args.wait_for_parent_dir), 'manifest_sha256': sha(args.wait_for_parent_dir / 'manifest.json')}
        if parent['pid'] != args.wait_for_parent_pid or parent['output_dir'] != str(args.wait_for_parent_dir):
            raise ValueError('original bound parent changed')
        helpers = [java_dir / n for n in ('OfflineTemporalReplayCli.java', 'FitOnlyValidationReplayCli.java', 'FixedSourcePrimaryReplayCli.java')]
        queue = frozen_queue(native.read_text(encoding='utf-8'), ready['symbols'])
        manifest = {'schema': 'frozen_directional_clock_100_scopes_v1', 'queue': queue, 'parent_identity': parent,
            'engineering_manifest_sha256': sha(args.engineering_dir / 'manifest.json'), 'regression_manifest_sha256': sha(args.regression_dir / 'manifest.json'),
            'source_sha256': source_hashes, 'classes_sha256': class_hashes, 'tool_sha256': frozen_tool_paths(args, helpers),
            'ready_sha256': sha(args.input_dir / 'READY.json'), 'training_ready_sha256': sha(args.training_input_dir / 'READY.json'),
            'fit_oracle_manifest_sha256': sha(args.fit_oracle_dir / 'manifest.json'), 'locked_oracle_manifest_sha256': locked['manifest_sha256'],
            'mechanism_group': 'directional_change_overshoot_clock', 'server_codegen_allowed': False, 'production_write': False}
        if previous is not None and previous != manifest: raise ValueError('frozen batch provenance changed')
        if previous is None: write_status(output / 'manifest.json', manifest)
        manifest_hash = sha(output / 'manifest.json')
        records = []
        try:
            while parent_alive(parent):
                write_status(output / 'status.json', {'state': 'WAITING_FOR_BOUND_PROFILE_BATCH', 'completed': 0,
                    'total': 100, 'parent_pid': parent['pid'], 'production_write': False})
                time.sleep(10)
            require_parent_complete(parent)
            require_hashes(manifest['tool_sha256']); require_hashes(source_hashes); require_hashes(class_hashes)
            classes = output / 'classes'; classes.mkdir(exist_ok=True)
            cp = str(classes) + os.pathsep + java_classpath(args.sim_repo)
            parity_cp = os.pathsep.join([str(args.engineering_dir / 'classes'), str(args.reference_indsvr_repo / 'target/test-classes'),
                str(args.reference_indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
            proof_records = {r['strategy']: r for r in read(args.engineering_dir / 'status.json')['records']}
            execute(['javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(classes)] + list(map(str, helpers)), output / 'helper-compile.log')
            for row in queue:
                resources = resource_state(output)
                while not resources['ready']:
                    write_status(output / 'status.json', {'state': 'WAITING_FOR_LOCAL_RESOURCES', 'completed': len(records),
                        'total': 100, 'resources': resources, 'production_write': False})
                    time.sleep(10); resources = resource_state(output)
                require_hashes(manifest['tool_sha256']); require_hashes(source_hashes)
                record = run_case(args, row, manifest_hash, ready, protocol, cp, parity_cp, proof_records,
                                  export_source=export_source, scope_fields=SCOPE_FIELDS)
                records.append(record)
                write_status(output / 'results.json', records)
                write_status(output / 'status.json', {'state': 'RUNNING', 'updated_utc': datetime.now(timezone.utc).isoformat(),
                    'completed': len(records), 'total': 100, 'local_formal_qualified': sum(r['qualified'] for r in records),
                    'published': 0, 'production_write': False})
                print('DIRECTIONAL_CLOCK_FORMAL', len(records), '/', 100, row['strategy'], record['reason'], flush=True)
            write_status(output / 'FORMAL_COMPLETE.json', {'manifest_sha256': manifest_hash, 'completed': 100,
                'local_formal_qualified': sum(r['qualified'] for r in records), 'production_write': False})
        except Exception as error:
            write_status(output / 'FAILED.json', {'completed': len(records), 'error': str(error), 'production_write': False}); raise


if __name__ == '__main__': main()
