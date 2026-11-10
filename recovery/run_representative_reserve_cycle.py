"""Continue unused fixed-source families only after the parent cycle and audit finish.

No fresh screen, parameter tuning or server code generation is performed. The
existing source-bound semantic review remains required before catalog imports.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from recovery.finalize_local_historical_scene_campaign import wait_for_process
from recovery.run_local_source_strategy_cycle import verify_resume_markers
from recovery.strategy_recovery_common import atomic_write_json


def require_parent_complete(parent):
    state = json.loads((parent / 'cycle-status.json').read_text(encoding='utf-8'))
    if state.get('stage') != 'cycle_complete' or state.get('state') != 'complete':
        raise ValueError('reserve requires completed parent cycle, including server inventory audit')
    verify_resume_markers(parent, 'server_import_backtest_audit')
    status = json.loads((parent / 'formal/status.json').read_text(encoding='utf-8'))
    shortlist = json.loads((parent / 'screen/shortlist.json').read_text(encoding='utf-8'))
    results = json.loads((parent / 'formal/results.json').read_text(encoding='utf-8'))
    keys = lambda rows: [(r['symbol'], r['scene'], r['hypothesis']) for r in rows]
    if (status.get('errors') or status.get('completed') != status.get('total')
            or status.get('total') != len(shortlist) or len(results) != len(shortlist)
            or sorted(keys(results)) != sorted(keys(shortlist))
            or len(set(keys(results))) != len(results)):
        raise ValueError('reserve requires all parent shortlisted financial outcomes, including failures')
    summary = json.loads((parent / 'formal/cycle-summary.json').read_text(encoding='utf-8'))
    if summary.get('local_formal_status') != status:
        raise ValueError('parent terminal inventory summary does not match completed formal status')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent-dir', 'output-dir', 'input-dir', 'indsvr-repo', 'sim-repo', 'snapshot', 'protocol'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--cohort', required=True)
    parser.add_argument('--backtest-end-date', required=True)
    parser.add_argument('--wait-pid', type=int)
    args = parser.parse_args()
    for name in ('parent_dir', 'output_dir', 'input_dir', 'indsvr_repo', 'sim_repo', 'snapshot', 'protocol'):
        setattr(args, name, getattr(args, name).resolve())
    if (args.output_dir == args.parent_dir or args.parent_dir in args.output_dir.parents
            or args.output_dir in args.parent_dir.parents):
        parser.error('reserve output must be a distinct, non-overlapping evidence directory')
    if args.wait_pid is not None and args.wait_pid <= 0:
        parser.error('--wait-pid must be positive')
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def status(stage, state):
        atomic_write_json(args.output_dir / 'cycle-status.json', {
            'stage': stage, 'state': state, 'parent_dir': str(args.parent_dir),
            'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'server_codegen_allowed': False})

    stage = 'waiting_for_parent_audit'
    try:
        status(stage, 'waiting')
        if args.wait_pid is not None:
            wait_for_process(args.wait_pid)
        require_parent_complete(args.parent_dir)
        classes = str(args.indsvr_repo / 'target/test-classes')
        validator = os.pathsep.join([classes, str(args.indsvr_repo / 'target/classes'),
            str(args.sim_repo / 'target/classes'), str(args.sim_repo / 'target/dependency/*')])
        commands = [
            ('verify_frozen_parent_catalog', ['recovery.run_representative_strategy_campaign',
                '--input-dir', str(args.input_dir), '--output-dir', str(args.parent_dir / 'screen'),
                '--classes', classes, '--indsvr-repo', str(args.indsvr_repo),
                '--snapshot', str(args.snapshot), '--protocol', str(args.protocol),
                '--cohort', args.cohort, '--prepare-only']),
            ('freeze_unconsumed_reserve', ['recovery.prepare_representative_reserve_queue',
                '--campaign-dir', str(args.parent_dir / 'screen'),
                '--formal-dir', str(args.parent_dir / 'formal'),
                '--output-dir', str(args.output_dir / 'screen')]),
            ('local_formal_holdout', ['recovery.run_representative_formal_batch',
                '--campaign-dir', str(args.output_dir / 'screen'), '--input-dir', str(args.input_dir),
                '--output-dir', str(args.output_dir / 'formal'), '--indsvr-repo', str(args.indsvr_repo),
                '--sim-repo', str(args.sim_repo), '--protocol', str(args.protocol), '--workers', '1']),
            ('server_import_backtest_audit', ['recovery.finish_representative_campaign',
                '--formal-dir', str(args.output_dir / 'formal'),
                '--server-dir', str(args.output_dir / 'server'),
                '--snapshot-dir', str(args.output_dir / 'inventory'),
                '--validator-classes', validator, '--backtest-end-date', args.backtest_end_date])]
        manifest = {'schema': 'fixed_reserve_cycle_v1', 'commands': commands,
                    'parent_campaign_sha256': hashlib.sha256(
                        (args.parent_dir / 'screen/campaign.json').read_bytes()).hexdigest(),
                    'parent_results_sha256': hashlib.sha256(
                        (args.parent_dir / 'formal/results.json').read_bytes()).hexdigest()}
        path = args.output_dir / 'manifest.json'
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) != json.loads(json.dumps(manifest)):
            raise ValueError('reserve inputs changed; preserve this batch and use a new output directory')
        atomic_write_json(path, manifest)
        for stage, command in commands:
            status(stage, 'running')
            print('STAGE', stage, flush=True)
            subprocess.run([sys.executable, '-u', '-m'] + command, check=True)
        status('cycle_complete', 'complete')
    except Exception:
        status(stage, 'failed')
        raise


if __name__ == '__main__':
    main()
