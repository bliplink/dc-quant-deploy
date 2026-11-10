"""Wait for the local reserve, qualify passing sources on the server, then audit inventory."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from recovery.finalize_local_historical_scene_campaign import wait_for_process
from recovery.run_local_historical_scene_campaign import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-pid', type=int, help='Optional Windows PID; omit only for an already-complete formal batch')
    parser.add_argument('--formal-dir', type=Path, required=True)
    parser.add_argument('--server-dir', type=Path, required=True)
    parser.add_argument('--snapshot-dir', type=Path, required=True)
    parser.add_argument('--validator-classes', required=True)
    parser.add_argument('--backtest-end-date', required=True)
    args = parser.parse_args()
    if args.wait_pid is not None and args.wait_pid <= 0:
        parser.error('--wait-pid must be positive')
    if args.wait_pid is not None:
        print('waiting for local formal batch', args.wait_pid, flush=True)
        wait_for_process(args.wait_pid)
    elif not (args.formal_dir / 'FORMAL_COMPLETE.json').exists():
        raise RuntimeError('without --wait-pid a complete formal batch is required')
    if not (args.formal_dir / 'results.json').exists():
        raise RuntimeError('formal batch has no completed result ledger')
    status = json.loads((args.formal_dir / 'status.json').read_text(encoding='utf-8'))
    print('local formal completed', status.get('completed'), '/', status.get('total'),
          'qualified', status.get('local_formal_qualified'), 'errors', len(status.get('errors', [])), flush=True)
    before_snapshot = args.snapshot_dir / 'before'
    subprocess.run([sys.executable, '-u', '-m', 'recovery.strategy_inventory_snapshot',
                    '--output-dir', str(before_snapshot)], check=True)
    subprocess.run([sys.executable, '-u', '-m', 'recovery.promote_qualified_catalog_candidates',
        '--formal-dir', str(args.formal_dir), '--output-dir', str(args.server_dir),
        '--backtest-end-date', args.backtest_end_date, '--limit', '0',
        '--inventory-snapshot', str(before_snapshot / 'active_strategy_qualification.tsv'),
        '--validator-classes', args.validator_classes], check=True)
    subprocess.run([sys.executable, '-u', '-m', 'recovery.strategy_inventory_snapshot',
                    '--output-dir', str(args.snapshot_dir)], check=True)
    inventory = json.loads((args.snapshot_dir / 'summary.json').read_text(encoding='utf-8'))
    review_path = args.server_dir / 'semantic-review-audit.json'
    review = json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else None
    write_json(args.formal_dir / 'cycle-summary.json', {
        'local_formal_status': status, 'production_inventory': inventory,
        'semantic_release_review': review,
        'qualified_inventory_gap': max(0, 100 - inventory['qualified_count']),
        'inventory_count_target_met': inventory['qualified_count'] >= 100,
        'source_independence_review_required': True})
    print('production qualified', inventory['qualified_count'], 'gap',
          max(0, 100 - inventory['qualified_count']), flush=True)


if __name__ == '__main__':
    main()
