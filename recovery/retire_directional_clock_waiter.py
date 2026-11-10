"""Retire only the exact audited zero-finance local waiter, never a calculation or service."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from recovery.run_directional_clock_parallel import observe_idle, original_context, require_hashes, verify_context
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.run_true_adx_batch import read
from recovery.verify_fit_only_risk_contract import sha


def retire(original, manifest_sha, pid, created, preflight, target):
    if target == original or target.parent != original.parent or not target.name.startswith('strategy-directional-clock-'):
        raise ValueError('explicit sibling clock-research output required')
    if target.exists(): raise ValueError('new financial root must not exist before retirement')
    if (original / 'ORCHESTRATION_HANDOFF.json').exists(): raise ValueError('prior handoff exists; inspect, never repeat termination')
    prepared = read(preflight / 'PREPARE_COMPLETE.json')
    controller = Path(__file__).with_name('run_directional_clock_parallel.py')
    if (prepared.get('original_manifest_sha256') != manifest_sha or prepared.get('controller_source_sha256') != sha(controller)
            or prepared.get('retirer_source_sha256') != sha(Path(__file__))
            or prepared.get('entire_queue_scopes') != 100 or prepared.get('source_and_helpers_unchanged') is not True
            or prepared.get('financial_dispatch_started') is not False or prepared.get('production_write') is not False):
        raise ValueError('complete unchanged local scheduling preflight required before stopping anything')
    process, manifest, status = observe_idle(original, manifest_sha, pid, created)
    identity = dict(pid=pid, create_time=created, command=process.cmdline())
    require_hashes(prepared['checked_tool_sha256'])
    verify_context(original_context(identity['command'], original), manifest)
    # Observe again immediately before termination. The bound parent is still well short of200.
    process, _, _ = observe_idle(original, manifest_sha, pid, created)
    process.terminate();process.wait(timeout=20)
    with exclusive_batch(original):
        record = dict(schema='zero_finance_clock_scheduling_handoff_v1', old_identity=identity,
            original_manifest_sha256=manifest_sha, original_completed=0, original_state=status['state'],
            calculation_children=[], financial_dispatch_ever_started=False, old_owner_stop_verified=True,
            controller_source_sha256=sha(controller), preflight_marker_sha256=sha(preflight / 'PREPARE_COMPLETE.json'),
            target_output_dir=str(target), retired_utc=datetime.now(timezone.utc).isoformat(),
            reason='replace logical parent waiting with one3GiB-guarded local slot; no source/rule/data or financial replay changes',
            production_write=False)
        write_status(original / 'ORCHESTRATION_HANDOFF.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-wait-dir', type=Path, required=True)
    parser.add_argument('--original-manifest-sha256', required=True)
    parser.add_argument('--waiting-pid', type=int, required=True)
    parser.add_argument('--waiting-create-time', type=float, required=True)
    parser.add_argument('--preflight-dir', type=Path, required=True)
    parser.add_argument('--target-output-dir', type=Path, required=True)
    args = parser.parse_args()
    record = retire(args.original_wait_dir.resolve(), args.original_manifest_sha256, args.waiting_pid,
                    args.waiting_create_time, args.preflight_dir.resolve(), args.target_output_dir.resolve())
    print('ZERO_FINANCE_WAITER_RETIRED', record['old_identity']['pid'], record['retired_utc'], flush=True)


if __name__ == '__main__': main()
