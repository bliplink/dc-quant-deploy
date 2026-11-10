"""Local source -> validation -> formal+holdout -> external import -> server replay.

This orchestrator has no server generation endpoint or model credentials. The
production key is inherited in memory solely for audited server operations.
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-dir', 'output-dir', 'indsvr-repo', 'sim-repo', 'snapshot', 'protocol'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--cohort', required=True)
    parser.add_argument('--backtest-end-date', required=True)
    args = parser.parse_args()
    for name in ('input_dir', 'output_dir', 'indsvr_repo', 'sim_repo', 'snapshot', 'protocol'):
        setattr(args, name, getattr(args, name).resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    screen, formal = args.output_dir / 'screen', args.output_dir / 'formal'
    classes = str(args.indsvr_repo / 'target/test-classes')
    # platform classpath separator is explicit; the server does not receive this local classpath.
    import os
    validator = os.pathsep.join([classes, str(args.indsvr_repo / 'target/classes'),
        str(args.sim_repo / 'target/classes'), str(args.sim_repo / 'target/dependency/*')])
    commands = [
        ('freeze_local_catalog', ['recovery.run_representative_strategy_campaign',
            '--input-dir', str(args.input_dir), '--output-dir', str(screen),
            '--classes', classes, '--indsvr-repo', str(args.indsvr_repo),
            '--snapshot', str(args.snapshot), '--protocol', str(args.protocol),
            '--cohort', args.cohort, '--prepare-only']),
        ('local_source_contract', ['recovery.validate_local_catalog_sources',
            '--campaign-dir', str(screen), '--indsvr-repo', str(args.indsvr_repo),
            '--sim-repo', str(args.sim_repo), '--input-dir', str(args.input_dir),
            '--output-dir', str(args.output_dir / 'source-contract')]),
        ('local_screen', ['recovery.run_representative_strategy_campaign',
            '--input-dir', str(args.input_dir), '--output-dir', str(screen),
            '--classes', classes, '--indsvr-repo', str(args.indsvr_repo),
            '--snapshot', str(args.snapshot), '--protocol', str(args.protocol),
            '--cohort', args.cohort, '--workers', '2']),
        ('local_formal_holdout', ['recovery.run_representative_formal_batch',
            '--campaign-dir', str(screen), '--input-dir', str(args.input_dir),
            '--output-dir', str(formal), '--indsvr-repo', str(args.indsvr_repo),
            '--sim-repo', str(args.sim_repo), '--protocol', str(args.protocol), '--workers', '1']),
        ('server_import_backtest_audit', ['recovery.finish_representative_campaign',
            '--formal-dir', str(formal), '--server-dir', str(args.output_dir / 'server'),
            '--snapshot-dir', str(args.output_dir / 'inventory'), '--validator-classes', validator,
            '--backtest-end-date', args.backtest_end_date]),
    ]
    for stage, command in commands:
        atomic_write_json(args.output_dir / 'cycle-status.json', {
            'stage': stage, 'state': 'running', 'cohort': args.cohort,
            'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'server_codegen_allowed': False, 'server_endpoint': 'dc.ind.strategy.candidate.import'})
        print('STAGE', stage, flush=True)
        completed = subprocess.run([sys.executable, '-u', '-m'] + command)
        if completed.returncode:
            atomic_write_json(args.output_dir / 'cycle-status.json', {
                'stage': stage, 'state': 'failed', 'exit_code': completed.returncode,
                'server_codegen_allowed': False})
            raise RuntimeError('cycle stage failed: ' + stage)
    atomic_write_json(args.output_dir / 'cycle-status.json', {
        'stage': 'cycle_complete', 'state': 'complete', 'server_codegen_allowed': False,
        'summary': str(formal / 'cycle-summary.json')})
    print('Cycle complete; production inventory is in', formal / 'cycle-summary.json', flush=True)


if __name__ == '__main__':
    main()
