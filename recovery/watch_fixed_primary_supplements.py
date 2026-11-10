"""Follow one verified legacy parent and add disjoint holdouts exactly once; never upload/publish."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from recovery.strategy_recovery_common import atomic_write_json
from recovery.temporal_admission_contract import require_temporally_isolated_admission
from recovery.verify_fit_only_risk_contract import sha


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def parent_identity(pid, formal_dir):
    process = psutil.Process(pid)
    command = process.cmdline()
    modules = {'recovery.run_representative_reserve_cycle': formal_dir.parent,
               'recovery.run_representative_formal_batch': formal_dir}
    if '-m' not in command or '--output-dir' not in command:
        raise ValueError('parent is not an explicit research module process')
    module = command[command.index('-m') + 1]
    output = Path(command[command.index('--output-dir') + 1]).resolve()
    if module not in modules or output != modules[module].resolve() or not process.is_running():
        raise ValueError('parent process identity/output mismatch')
    return {'pid': pid, 'create_time': process.create_time(), 'command': command}


def parent_alive(identity):
    try:
        process = psutil.Process(identity['pid'])
        return (process.is_running() and process.create_time() == identity['create_time']
                and process.cmdline() == identity['command'])
    except psutil.NoSuchProcess:
        return False


def coherent_parent_snapshot(formal_dir):
    """The legacy writer saves status then results; never consume a torn checkpoint."""
    try:
        before = (formal_dir / 'status.json').read_bytes()
        records = read(formal_dir / 'results.json')
        after = (formal_dir / 'status.json').read_bytes()
        status = json.loads(before)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if before != after or status['completed'] != len(records):
        return None
    if len({row['strategy'] for row in records}) != len(records):
        raise ValueError('duplicate parent financial record')
    if status.get('errors'):
        raise ValueError('parent reports execution/parity errors; diagnose before continuing')
    if sum(row['qualified'] for row in records) != status['local_formal_qualified']:
        raise ValueError('parent qualification count mismatch')
    return status, records


def completed_parent(formal_dir, status, records):
    marker = formal_dir / 'FORMAL_COMPLETE.json'
    if not marker.exists():
        return False
    complete = read(marker)
    if (complete['manifest_sha256'] != sha(formal_dir / 'manifest.json')
            or complete['completed'] != len(records) or len(records) != status['total']
            or complete['local_formal_qualified'] != status['local_formal_qualified']
            or complete.get('production_write') is not False):
        raise ValueError('parent completion does not prove every financial outcome was retained')
    return True


def verified_supplement(directory, original, bindings):
    if not (directory / 'FORMAL_COMPLETE.json').exists():
        raise ValueError('partial supplementary attempt; never rerun an inspected/ambiguous holdout: ' + str(directory))
    manifest = read(directory / 'manifest.json')
    if (read(directory / 'FORMAL_COMPLETE.json')['manifest_sha256'] != sha(directory / 'manifest.json')
            or manifest['primary_envelope_sha256'] != sha(Path(original['result_path']))
            or manifest['strategy'] != original['strategy'] or manifest['source_sha256'] != original['source_sha256']
            or manifest['protocol_sha256'] != bindings['protocol_sha256']
            or manifest['ready_sha256'] != bindings['ready_sha256']
            or manifest['oracle_manifest_sha256'] != bindings['oracle_manifest_sha256']
            or manifest['helper_source_sha256'] != bindings['helper_source_sha256']
            or manifest.get('primary_pnl_rerun') is not False or manifest.get('production_write') is not False):
        raise ValueError('supplement is not bound to exact untouched primary/source/protocol')
    records = read(directory / 'results.json')
    if len(records) != 1:
        raise ValueError('one exact source per supplementary attempt is required')
    record = records[0]
    if any(record[key] != original[key] for key in ('strategy', 'source_sha256', 'symbol', 'scene', 'hypothesis', 'family')):
        raise ValueError('supplementary source/scope mismatch')
    admission = read(Path(record['result_path']))
    require_temporally_isolated_admission(admission, require_risk_profile=False)
    source_sha = hashlib.sha256(Path(admission['sourceFile']).read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    if (source_sha != original['source_sha256'] or admission['sourceSha256'] != source_sha
            or admission['result']['qualified'] != record['qualified']
            or record['qualified'] != admission['result']['holdout']['passed']):
        raise ValueError('supplement result/source changed')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('formal-dir', 'input-dir', 'protocol', 'sim-repo', 'oracle-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--reuse-result-dir', type=Path, action='append', default=[])
    parser.add_argument('--poll-seconds', type=int, default=10, choices=range(5, 61))
    args = parser.parse_args()
    for name in ('formal_dir', 'input_dir', 'protocol', 'sim_repo', 'oracle_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if output.exists():
        raise ValueError('watch attempt must be new; reuse its finished results explicitly instead of replaying')
    identity = parent_identity(args.parent_pid, args.formal_dir)
    helper = Path(__file__).with_name('java') / 'OfflineTemporalReplayCli.java'
    supplement = Path(__file__).with_name('supplement_temporal_holdout.py')
    bindings = {'protocol_sha256': sha(args.protocol), 'ready_sha256': sha(args.input_dir / 'READY.json'),
                'oracle_manifest_sha256': sha(args.oracle_dir / 'manifest.json'), 'helper_source_sha256': sha(helper)}
    reuse = {}
    for directory in args.reuse_result_dir:
        directory = directory.resolve()
        name = read(directory / 'manifest.json')['strategy']
        if name in reuse:
            raise ValueError('multiple old supplementary attempts for one source')
        reuse[name] = directory
    output.mkdir(parents=True)
    manifest = dict(bindings, schema='verified_legacy_source_supplement_watcher_v1', parent=identity,
        parent_manifest_sha256=sha(args.formal_dir / 'manifest.json'), watcher_sha256=sha(Path(__file__)),
        supplement_tool_sha256=sha(supplement), psutil_version=psutil.__version__,
        reuse_results={key: {'directory': str(directory), 'manifest_sha256': sha(directory / 'manifest.json'),
            'results_sha256': sha(directory / 'results.json')} for key, directory in reuse.items()},
        production_write=False, server_codegen_allowed=False)
    atomic_write_json(output / 'manifest.json', manifest)
    atomic_write_json(output / 'results.json', [])
    results, seen, previous_records = [], {}, {}
    try:
        while True:
            if (sha(args.formal_dir / 'manifest.json') != manifest['parent_manifest_sha256']
                    or sha(supplement) != manifest['supplement_tool_sha256']
                    or sha(helper) != bindings['helper_source_sha256']):
                raise ValueError('frozen parent or replay tool changed during watch')
            snapshot = coherent_parent_snapshot(args.formal_dir)
            if snapshot is None:
                if not parent_alive(identity):
                    raise ValueError('verified parent exited without a coherent financial ledger')
                time.sleep(args.poll_seconds)
                continue
            status, records = snapshot
            current_records = {row['strategy']: row for row in records}
            if any(name not in current_records or current_records[name] != row
                   for name, row in previous_records.items()):
                raise ValueError('parent discarded or changed a completed observation, including a failure')
            previous_records = current_records
            for original in records:
                name = original['strategy']
                if name in seen and seen[name] != original:
                    raise ValueError('previously consumed parent observation changed')
                if not original['qualified'] or name in seen:
                    continue
                directory = reuse.get(name, output / 'candidates' / name)
                if not directory.exists():
                    log = output / 'logs' / (name + '.log')
                    log.parent.mkdir(parents=True, exist_ok=True)
                    command = [sys.executable, '-u', '-m', 'recovery.supplement_temporal_holdout',
                        '--formal-dir', str(args.formal_dir), '--strategy', name, '--input-dir', str(args.input_dir),
                        '--protocol', str(args.protocol), '--sim-repo', str(args.sim_repo),
                        '--oracle-dir', str(args.oracle_dir), '--output-dir', str(directory)]
                    with log.open('w', encoding='utf-8') as stream:
                        completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=1200)
                    if completed.returncode:
                        raise RuntimeError('supplementary execution failed; inspect ' + str(log))
                record = verified_supplement(directory, original, bindings)
                frozen = output / 'frozen' / name
                frozen.mkdir(parents=True, exist_ok=True)
                for filename in ('GeneratedStrategy.java', 'seed.json'):
                    (frozen / filename).write_bytes((directory / 'frozen' / name / filename).read_bytes())
                results.append(dict(record, supplementary_dir=str(directory), original_result_reused=name in reuse))
                seen[name] = original
                atomic_write_json(output / 'results.json', results)
                print('FIXED_SOURCE_SUPPLEMENT', name, 'qualified', record['qualified'], 'reused', name in reuse, flush=True)
            complete = completed_parent(args.formal_dir, status, records)
            current = {'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'parent_completed': status['completed'], 'parent_total': status['total'],
                'legacy_passes_seen': len(results), 'local_formal_qualified': sum(r['qualified'] for r in results),
                'parent_terminal': complete, 'published': 0, 'production_write': False}
            atomic_write_json(output / 'status.json', current)
            if complete:
                atomic_write_json(output / 'WATCH_COMPLETE.json', dict(current, manifest_sha256=sha(output / 'manifest.json')))
                break
            if not parent_alive(identity):
                raise ValueError('verified parent exited without FORMAL_COMPLETE; preserve pending work for diagnosis')
            time.sleep(args.poll_seconds)
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', {'error': str(error), 'handled_sources': len(results), 'production_write': False})
        raise


if __name__ == '__main__':
    main()
