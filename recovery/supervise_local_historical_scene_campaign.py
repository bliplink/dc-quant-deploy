"""Resume an interrupted local scene campaign only for explicit model capacity errors.

This watcher never writes production data. All resumed work uses the same pinned
campaign manifest and the normal checkpoint/hash/READY validation path.
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from recovery.finalize_local_historical_scene_campaign import require_completed, wait_for_process
from recovery.assemble_local_historical_scene_input import assemble
from recovery.run_local_historical_scene_campaign import hit_model_capacity


def may_resume_capacity(status, campaign_dir):
    failed = status.get('failed_chunk')
    if not failed or status.get('completed_chunks') == status.get('total_chunks'):
        return False
    chunk = Path(failed).resolve()
    if campaign_dir.resolve() not in chunk.parents:
        raise ValueError('failed chunk is outside the pinned campaign')
    attempts = sorted(chunk.glob('attempt_*'), reverse=True)
    return bool(attempts and hit_model_capacity(attempts[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-pid', type=int, required=True)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--campaign-dir', type=Path, required=True)
    parser.add_argument('--indsvr-repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.wait_pid <= 0:
        parser.error('--wait-pid must be positive')
    print('supervising scene campaign pid', args.wait_pid, flush=True)
    wait_for_process(args.wait_pid)
    status_path = args.campaign_dir / 'status.json'
    status = json.loads(status_path.read_text(encoding='utf-8'))
    if status.get('completed_chunks') == status.get('total_chunks'):
        # The original finalizer owns this successful run.
        require_completed(status_path)
        print('original campaign complete; original finalizer owns READY', flush=True)
        return
    if not may_resume_capacity(status, args.campaign_dir):
        raise RuntimeError('campaign stopped for a non-capacity reason; inspect ' + str(status_path))
    manifest = json.loads((args.campaign_dir / 'campaign.json').read_text(encoding='utf-8'))
    command = [sys.executable, '-u', '-m', 'recovery.run_local_historical_scene_campaign',
               '--input-dir', str(args.input_dir), '--output-dir', str(args.campaign_dir),
               '--indsvr-repo', str(args.indsvr_repo), '--begin', manifest['begin'],
               '--end', manifest['end'], '--symbols', ','.join(manifest['symbols']),
               '--model', manifest['model'], '--chunk-days', str(manifest['chunk_days']),
               '--timeout-minutes', '15', '--retry-failed', '--wait-on-usage-limit',
               '--quota-retry-minutes', '60', '--wait-on-model-capacity',
               '--capacity-retry-minutes', '15']
    print('resuming pinned campaign after explicit model capacity failure', flush=True)
    subprocess.run(command, check=True)
    require_completed(status_path)
    metadata = assemble(args.input_dir.resolve(), args.campaign_dir.resolve(),
                        args.output_dir.resolve(), date(2025, 10, 12))
    print('READY', args.output_dir, 'symbols', len(metadata['symbols']), flush=True)


if __name__ == '__main__':
    main()
