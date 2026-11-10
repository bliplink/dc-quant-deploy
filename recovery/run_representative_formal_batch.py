"""Freeze, compare signals, and formally replay shortlisted local catalog candidates.

Every completed financial result is checkpointed, including failures. This tool
does not publish; production candidate generation/requalification remains separate.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import paramiko

from recovery import local_strategy_backtest as runner
from recovery.export_representative_candidate import export_candidate
from recovery.run_local_historical_scene_campaign import write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def research_parity_classpath(indsvr_repo, sim_repo):
    return os.pathsep.join([str(indsvr_repo / 'target/test-classes'),
                           str(indsvr_repo / 'target/classes'), runner.java_classpath(sim_repo)])


def write_empty_formal_batch(output, manifest_hash):
    """An empty validation shortlist is a completed zero-result batch, not an error."""
    write_json(output / 'results.json', [])
    write_json(output / 'status.json', {
        'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'completed': 0, 'total': 0, 'local_formal_qualified': 0, 'published': 0, 'errors': []})
    write_json(output / 'FORMAL_COMPLETE.json', {
        'manifest_sha256': manifest_hash, 'completed': 0,
        'local_formal_qualified': 0, 'production_write': False})


def validation_windows(scene):
    fit, validate, forward = ((90, 30, 14) if scene == 'range' else
                             (120, 20, 10) if scene in ('breakout', 'reversal') else (120, 30, 14))
    first, stop = date(2024, 12, 15), date(2025, 8, 12)
    begin = first + timedelta(days=fit)
    while begin + timedelta(days=validate + forward) <= stop:
        yield begin.isoformat(), (begin + timedelta(days=validate - 1)).isoformat()
        begin += timedelta(days=validate + forward)


def run_one(args, item, db_config, manifest_hash, pilot):
    symbol, scene, hypothesis = item['symbol'], item['scene'], item['hypothesis']
    identity = hashlib.sha256((symbol + ':' + scene + ':' + hypothesis).encode()).hexdigest()[:16]
    output = args.output_dir / 'candidates' / identity
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / 'checkpoint.json'
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if saved['manifest_sha256'] != manifest_hash:
            raise ValueError('formal checkpoint manifest changed')
        return saved
    if pilot and all(pilot['frozen'][key] == item[key] for key in ('symbol', 'scene', 'hypothesis')):
        envelope = json.loads(args.pilot_result.read_text(encoding='utf-8'))
        normalized_source = Path(envelope['sourceFile']).read_text(encoding='utf-8')
        if hashlib.sha256(normalized_source.encode('utf-8')).hexdigest() != pilot['frozen']['source_sha256']:
            raise ValueError('pilot frozen source hash changed')
        record = {'symbol': symbol, 'scene': scene, 'hypothesis': hypothesis,
                  'strategy': envelope['strategyName'], 'result_path': str(args.pilot_result),
                  'qualified': bool(envelope['result']['qualified']),
                  'reason': envelope['result']['qualificationReason'], 'pilot_reused': True,
                  'manifest_sha256': manifest_hash, 'production_write': False}
        write_json(checkpoint, record)
        return record
    frozen_dir, name = export_candidate(args.campaign_dir, args.indsvr_repo,
                                        args.output_dir / 'frozen', symbol, scene, hypothesis)
    source = (frozen_dir / 'GeneratedStrategy.java').read_text(encoding='utf-8')
    artifact, entry_class, _ = runner.compile_source(source, args.sim_repo, output / 'parity-artifact')
    parity_cp = research_parity_classpath(args.indsvr_repo, args.sim_repo)
    with (output / 'signal-parity.log').open('w', encoding='utf-8') as log:
        for begin, end in validation_windows(scene):
            command = ['java', '-Xmx256m', '-Duser.timezone=UTC', '-cp', parity_cp,
                       'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
                       str(args.input_dir / (symbol + '-15m.tsv')), symbol, begin, end,
                       hypothesis, str(artifact), entry_class]
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            if completed.returncode:
                raise RuntimeError('signal parity failed: ' + str(output / 'signal-parity.log'))
    command = [sys.executable, '-u', '-m', 'recovery.local_strategy_backtest',
               '--strategy', name, '--seed', str(frozen_dir / 'seed.json'),
               '--source', str(frozen_dir / 'GeneratedStrategy.java'),
               '--sim-repo', str(args.sim_repo), '--local-research-input-dir', str(args.input_dir),
               '--older-protocol', str(args.protocol), '--begin-date', '2024-12-15',
               '--end-date', '2025-10-12', '--output-dir', str(output / 'formal'),
               '--db-config', str(db_config), '--java-heap-mb', '768', '--include-validate-trades']
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=1800)
    (output / 'formal.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    results = [line.split('=', 1)[1].strip() for line in completed.stdout.splitlines()
               if line.startswith('LOCAL_PRE_ADMISSION_RESULT=')]
    if completed.returncode not in (0, 2) or len(results) != 1:
        raise RuntimeError('formal replay execution failed: ' + str(output / 'formal.log'))
    envelope = json.loads(Path(results[0]).read_text(encoding='utf-8'))
    result = envelope['result']
    if envelope['productionWrite'] is not False or result.get('marketDataSource') != 'local_ready_tsv':
        raise ValueError('unexpected formal replay data/write contract')
    if result['qualified'] and not (result.get('holdout') or {}).get('passed'):
        raise ValueError('qualified result lacks a passing chronological holdout')
    record = {'symbol': symbol, 'scene': scene, 'hypothesis': hypothesis, 'strategy': name,
              'family': item['family'], 'result_path': results[0], 'qualified': bool(result['qualified']),
              'validation_net_bps': float(item['wf_validate_bps']),
              'reason': result['qualificationReason'], 'manifest_sha256': manifest_hash,
              'source_sha256': sha(frozen_dir / 'GeneratedStrategy.java'), 'production_write': False}
    write_json(checkpoint, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign-dir', 'input-dir', 'output-dir', 'indsvr-repo', 'sim-repo', 'protocol'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--pilot-result', type=Path)
    parser.add_argument('--pilot-frozen', type=Path)
    parser.add_argument('--workers', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.workers <= 2:
        parser.error('workers must be 1..2')
    for name in ('campaign_dir', 'input_dir', 'output_dir', 'indsvr_repo', 'sim_repo', 'protocol'):
        setattr(args, name, getattr(args, name).resolve())
    complete = json.loads((args.campaign_dir / 'SCREEN_COMPLETE.json').read_text(encoding='utf-8'))
    if complete.get('screen_holdout_withheld', complete.get('holdout_withheld')) is not True:
        raise ValueError('screen campaign did not withhold chronological holdout')
    items = json.loads((args.campaign_dir / 'shortlist.json').read_text(encoding='utf-8'))
    manifest = {'shortlist_sha256': sha(args.campaign_dir / 'shortlist.json'),
                'ready_sha256': sha(args.input_dir / 'READY.json'),
                'protocol_sha256': sha(args.protocol),
                'exporter_sha256': sha(Path(__file__).with_name('export_representative_candidate.py')),
                'formal_wrapper_sha256': sha(Path(__file__).with_name('local_strategy_backtest.py')),
                'local_cli_sha256': sha(args.sim_repo / 'target/test-classes/com/app/dc/service/simulation/LocalBacktestCli.class'),
                'production_write': False, 'target_candidates': len(items)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / 'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
        raise ValueError('formal batch inputs changed; use a new output directory')
    write_json(manifest_path, manifest)
    if not items:
        write_empty_formal_batch(args.output_dir, sha(manifest_path))
        print('Empty validation shortlist; formal complete with zero candidates', flush=True)
        return
    pilot = None
    if args.pilot_result:
        if not args.pilot_frozen:
            parser.error('--pilot-result requires --pilot-frozen')
        pilot = {'frozen': json.loads(args.pilot_frozen.read_text(encoding='utf-8'))}
    client, server, db_config = None, None, None
    records, errors = [], []
    try:
        client = paramiko.SSHClient()
        client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(runner.DEFAULT_HOST, username=runner.DEFAULT_USER,
                       key_filename=runner.DEFAULT_KEY,
                       passphrase=os.environ.pop('STC_PROD_KEY_PASSPHRASE'),
                       look_for_keys=False, allow_agent=False, timeout=20)
        client.get_transport().set_keepalive(20)
        remote_env = runner.read_remote_env(client)
        runner.ForwardHandler.ssh_transport = client.get_transport()
        runner.ForwardHandler.remote_port = int(remote_env.get('CLICKHOUSE_HTTP_PORT') or 8123)
        server = runner.ForwardServer(('127.0.0.1', 0), runner.ForwardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.NamedTemporaryFile(prefix='dc-catalog-formal-', suffix='.ini', delete=False) as handle:
            db_config = Path(handle.name)
        runner.write_db_config(db_config, server.server_address[1], remote_env)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            tasks = {executor.submit(run_one, args, item, db_config, sha(manifest_path), pilot): item
                     for item in items}
            for future in as_completed(tasks):
                item = tasks[future]
                try:
                    record = future.result()
                    records.append(record)
                    print(record['symbol'], record['scene'], record['hypothesis'], record['reason'], flush=True)
                except Exception as error:
                    errors.append({**item, 'error': str(error)})
                    print('ERROR', item['symbol'], item['hypothesis'], str(error), flush=True)
                write_json(args.output_dir / 'status.json', {
                    'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'completed': len(records), 'total': len(items),
                    'local_formal_qualified': sum(record['qualified'] for record in records),
                    'published': 0, 'errors': errors})
                write_json(args.output_dir / 'results.json', records)
        if not errors:
            write_json(args.output_dir / 'FORMAL_COMPLETE.json', {'manifest_sha256': sha(manifest_path),
                        'completed': len(records), 'local_formal_qualified': sum(r['qualified'] for r in records),
                        'production_write': False})
        else:
            raise RuntimeError('formal batch contains execution/parity failures; inspect status.json')
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if client is not None:
            client.close()
        if db_config is not None:
            db_config.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
