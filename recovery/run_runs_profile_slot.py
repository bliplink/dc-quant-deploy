"""Reuse a genuinely completed profile slot for an untouched signed-runs queue; unchanged finance."""
import argparse
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
import time

import psutil

from recovery import run_runs_clustering_batch as original
from recovery.research_control_handoff import calculation_children, drain_and_stop, identity, read
from recovery.run_directional_clock_parallel import option
from recovery.run_fit_risk_catalog_batch import exclusive_batch, write_status
from recovery.verify_fit_only_risk_contract import sha
from recovery.watch_fixed_primary_supplements import parent_alive

WAIT_MODULE = 'recovery.run_runs_clustering_batch'
PROFILE_MODULE = 'recovery.run_ohlcv_profile_proxy_batch'
PROFILE_SCHEMA = 'frozen_ohlcv_profile_proxy_200_scopes_v1'
PATHS = ('indsvr-repo','reference-indsvr-repo','sim-repo','training-input-dir','input-dir',
         'protocol','engineering-dir','fit-oracle-dir','locked-oracle-dir')


def exact_command(command, module, output):
    if (command.count('-m') != 1 or command[command.index('-m')+1] != module
            or Path(option(command,'output-dir')).resolve() != output):
        raise ValueError('exact module and output command required')


def context(command, output):
    exact_command(command,WAIT_MODULE,output)
    values = {key.replace('-','_'):Path(option(command,key)).resolve() for key in PATHS}
    binding = Path(option(command,'parent-binding')).resolve() if '--parent-binding' in command else None
    return Namespace(**values,output_dir=output,
        engineering_manifest_sha256=option(command,'engineering-manifest-sha256'),
        parent_binding=binding,parent_binding_sha256=option(command,'parent-binding-sha256') if binding else None)


def zero_plan(folder, digest):
    if sha(folder/'manifest.json') != digest: raise ValueError('original signed-runs manifest changed')
    manifest,status=read(folder/'manifest.json'),read(folder/'status.json')
    if (manifest.get('schema')!='frozen_runs_clustering_100_scopes_v1'
            or len(manifest.get('queue',[]))!=100 or len({r['strategy'] for r in manifest['queue']})!=100
            or status.get('state')!='WAITING_FOR_BOUND_CUSUM_BATCH'
            or status.get('completed')!=0 or status.get('total')!=100):
        raise ValueError('only original zero-dispatch signed-runs waiter can migrate')
    forbidden=('candidates','classes','frozen','results.json','FAILED.json','FORMAL_COMPLETE.json','ORCHESTRATION_HANDOFF.json')
    if any((folder/n).exists() for n in forbidden) or list(folder.rglob('*STARTED.json')):
        raise ValueError('old source or financial work started; preserve it, never duplicate')
    return manifest,status


def observe_idle(folder,digest,pid,created,allow_paused=False):
    manifest,status=zero_plan(folder,digest); process=psutil.Process(pid)
    if process.create_time()!=created: raise ValueError('old waiter PID reused')
    exact_command(process.cmdline(),WAIT_MODULE,folder)
    if not allow_paused and process.status()==psutil.STATUS_STOPPED:
        raise ValueError('already suspended owner must not be taken over')
    if calculation_children(process): raise ValueError('old waiter has calculation children')
    if not allow_paused and not parent_alive(manifest['parent_identity']):
        raise ValueError('original CUSUM parent may release waiter; defer and inspect')
    return process,manifest,status


def bind_profile(folder,digest,pid,created):
    if sha(folder/'manifest.json')!=digest or read(folder/'manifest.json').get('schema')!=PROFILE_SCHEMA:
        raise ValueError('exact frozen profile slot identity required')
    process=psutil.Process(pid)
    if process.create_time()!=created: raise ValueError('profile PID reused')
    exact_command(process.cmdline(),PROFILE_MODULE,folder)
    return dict(identity(process),output_dir=str(folder),manifest_sha256=digest)


def profile_complete(bound):
    folder=Path(bound['output_dir']);digest=bound['manifest_sha256']
    if parent_alive(bound): raise ValueError('profile slot owner must exit naturally before replacement')
    try:
        if psutil.pid_exists(bound['pid']) and psutil.Process(bound['pid']).create_time()==bound['create_time']:
            raise ValueError('profile PID still lives even if its command changed; do not reclaim its slot')
    except psutil.NoSuchProcess:
        pass
    manifest,marker,status=read(folder/'manifest.json'),read(folder/'FORMAL_COMPLETE.json'),read(folder/'status.json')
    queue=manifest.get('queue',[])
    if (sha(folder/'manifest.json')!=digest or manifest.get('schema')!=PROFILE_SCHEMA
            or marker.get('manifest_sha256')!=digest or marker.get('completed')!=200
            or marker.get('production_write') is not False or status.get('completed')!=200 or status.get('total')!=200
            or len(queue)!=200 or len({r['strategy'] for r in queue})!=200 or (folder/'FAILED.json').exists()):
        raise ValueError('profile must genuinely complete200; exit or a partial marker is insufficient')
    checkpoints={}; qualified=0
    for row in queue:
        case=folder/'candidates'/row['strategy']; saved=original.completed_case(case,digest)
        if any(saved.get(k)!=v for k,v in row.items()): raise ValueError('profile completed source scope or mode changed')
        qualified+=bool(saved['qualified']);checkpoints[row['strategy']]=sha(case/'checkpoint.json')
    if marker.get('local_formal_qualified')!=qualified or status.get('local_formal_qualified')!=qualified:
        raise ValueError('profile qualification counts disagree with original checkpoints')
    return dict(profile_identity=bound,completed=200,qualified=qualified,checkpoint_sha256=checkpoints,
        financial_observations_reexecuted=0,production_write=False)


def source_context(command,folder,manifest):
    args=context(command,folder);before=manifest['verification']
    original.check_snapshot(before)
    roots={Path(p).parent for p in before['tool_sha256'] if Path(p).name=='run_runs_clustering_batch.py'}
    if len(roots)!=1: raise ValueError('one exact original runtime tools root required')
    old_root=roots.pop();new_root=Path(__file__).parent
    expected={Path(p) for p in before['tool_sha256'] if Path(p).parent==old_root and Path(p).suffix=='.py'}
    if expected!=set(old_root.glob('*.py')): raise ValueError('original Python membership changed')
    for old in expected:
        if sha(new_root/old.name)!=before['tool_sha256'][str(old)]:
            raise ValueError('actual copied financial or source dependency differs: '+old.name)
    proof,ready,protocol=original.verify_context(args)
    excluded={'tool_sha256'}
    if {k:v for k,v in proof.items() if k not in excluded}!={k:v for k,v in before.items() if k not in excluded}:
        raise ValueError('entire original sources/classes/runtime/data/protocol/engine proofs must match')
    if original.frozen_queue(original.source_file(args.indsvr_repo).read_text(encoding='utf-8'),ready['symbols'])!=manifest['queue']:
        raise ValueError('entire original100 scope queue required')
    proof['tool_sha256'].update(before['tool_sha256'])
    return args,proof,ready,protocol


def old_stopped(bound):
    try:
        if psutil.pid_exists(bound['pid']) and psutil.Process(bound['pid']).create_time()==bound['create_time']:
            raise ValueError('old waiter still lives; no second financial owner')
    except psutil.NoSuchProcess:
        pass


def retire(args,prepared,proof):
    old=args.original_wait_dir; target=args.output_dir
    if target==old or target.parent!=old.parent or not target.name.startswith('strategy-runs-clustering-'):
        raise ValueError('explicit distinct sibling signed-runs output required')
    if target.exists(): raise ValueError('fresh financial output required before retirement')
    process,manifest,status=observe_idle(old,args.original_manifest_sha256,args.waiting_pid,args.waiting_create_time)
    if identity(process)!=prepared['old_identity']: raise ValueError('original waiting owner changed')
    slot=profile_complete(prepared['profile_identity'])
    _,current,_,_=source_context(process.cmdline(),old,manifest)
    if current!=proof: raise ValueError('prepared source/runtime context changed')
    claim=old/'ORCHESTRATION_HANDOFF_CLAIM.json'
    with claim.open('x',encoding='utf-8') as stream:
        import json
        json.dump(dict(owner=identity(psutil.Process()),control_dir=str(args.control_dir),target=str(target),
            original_manifest_sha256=args.original_manifest_sha256,production_write=False),stream)
    retirement=args.control_dir/'retirement';retirement.mkdir()
    def suspended_zero_checkpoint():
        _,frozen,_=observe_idle(old,args.original_manifest_sha256,args.waiting_pid,args.waiting_create_time,allow_paused=True)
        _,fresh,_,_=source_context(prepared['old_identity']['command'],old,frozen)
        if fresh!=proof: raise ValueError('context changed before stopping suspended owner')
        verified=profile_complete(prepared['profile_identity'])
        if verified!=slot: raise ValueError('profile release proof changed during transfer')
        return dict(original_manifest_sha256=args.original_manifest_sha256,original_completed=0,
            financial_dispatch_ever_started=False,profile_completion_audit=verified,production_write=False)
    checkpoint=drain_and_stop(prepared['old_identity'],retirement,suspended_zero_checkpoint,timeout=30)
    old_stopped(prepared['old_identity'])
    handoff=dict(schema='zero_finance_runs_profile_slot_handoff_v1',old_identity=prepared['old_identity'],
        original_manifest_sha256=args.original_manifest_sha256,original_completed=0,
        financial_dispatch_ever_started=False,old_owner_stop_verified=True,calculation_children=[],
        profile_completion_audit=checkpoint['profile_completion_audit'],
        guardian_intent_sha256=sha(retirement/'HANDOFF_INTENT.json'),
        guardian_checkpoint_sha256=sha(retirement/'HANDOFF_CHECKPOINT.json'),
        controller_source_sha256=sha(Path(__file__)),target_output_dir=str(target),
        retired_utc=datetime.now(timezone.utc).isoformat(),production_write=False)
    write_status(old/'ORCHESTRATION_HANDOFF.json',handoff)
    return handoff


def dispatch(args,prepared,proof,ready,protocol,finance_args):
    handoff=retire(args,prepared,proof)
    old_stopped(prepared['old_identity']);original.check_snapshot(proof)
    args.output_dir.mkdir()
    with exclusive_batch(args.original_wait_dir),exclusive_batch(args.output_dir):
        manifest=dict(schema='frozen_runs_clustering_profile_replacement_100_scopes_v1',
            queue=prepared['queue'],verification=proof,original_wait_dir=str(args.original_wait_dir),
            original_manifest_sha256=args.original_manifest_sha256,
            handoff_sha256=sha(args.original_wait_dir/'ORCHESTRATION_HANDOFF.json'),
            profile_slot_identity=prepared['profile_identity'],added_financial_slots=0,replacement_serial_slots=1,
            source_policy_changed=False,financial_rules_changed=False,financial_observations_reexecuted=0,
            mechanism_group='conditional_signed_runs_clustering',server_codegen_allowed=False,production_write=False)
        write_status(args.output_dir/'manifest.json',manifest);finance_args.output_dir=args.output_dir
        original.run_finance(finance_args,manifest,sha(args.output_dir/'manifest.json'),ready,protocol)
    write_status(args.control_dir/'CONTROLLER_COMPLETE.json',dict(completed=100,production_write=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('original-wait-dir','profile-dir','control-dir','output-dir'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('original-manifest-sha256','profile-manifest-sha256'):parser.add_argument('--'+name,required=True)
    for name in ('waiting-pid','profile-pid'):parser.add_argument('--'+name,type=int,required=True)
    for name in ('waiting-create-time','profile-create-time'):parser.add_argument('--'+name,type=float,required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare-only',action='store_true');modes.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    for name in ('original_wait_dir','profile_dir','control_dir','output_dir'):setattr(args,name,getattr(args,name).resolve())
    if args.output_dir.exists():raise ValueError('financial root must remain new; never blind resume financial attempts')
    if args.prepare_only:
        if args.control_dir.exists():raise ValueError('fresh preparation directory required')
        process,manifest,_=observe_idle(args.original_wait_dir,args.original_manifest_sha256,args.waiting_pid,args.waiting_create_time)
        profile=bind_profile(args.profile_dir,args.profile_manifest_sha256,args.profile_pid,args.profile_create_time)
        _,proof,_,_=source_context(process.cmdline(),args.original_wait_dir,manifest)
        args.control_dir.mkdir()
        prepared=dict(schema='runs_profile_slot_preparation_v1',old_identity=identity(process),profile_identity=profile,
            original_manifest_sha256=args.original_manifest_sha256,queue=manifest['queue'],verification=proof,
            controller_source_sha256=sha(Path(__file__)),target_output_dir=str(args.output_dir),
            financial_dispatch_started=False,production_write=False)
        write_status(args.control_dir/'PREPARE_COMPLETE.json',prepared)
        print('RUNS_PROFILE_SLOT_PREPARED100; no owner stopped or finance dispatched',flush=True);return
    prepared=read(args.control_dir/'PREPARE_COMPLETE.json')
    if (prepared.get('schema')!='runs_profile_slot_preparation_v1' or prepared.get('controller_source_sha256')!=sha(Path(__file__))
            or prepared.get('original_manifest_sha256')!=args.original_manifest_sha256
            or prepared.get('target_output_dir')!=str(args.output_dir)
            or prepared['old_identity']['pid']!=args.waiting_pid or prepared['old_identity']['create_time']!=args.waiting_create_time
            or prepared['profile_identity']['pid']!=args.profile_pid or prepared['profile_identity']['create_time']!=args.profile_create_time
            or prepared['profile_identity']['output_dir']!=str(args.profile_dir)
            or prepared['profile_identity']['manifest_sha256']!=args.profile_manifest_sha256):
        raise ValueError('exact prepared owner/profile/source/target required')
    with exclusive_batch(args.control_dir):
        if any((args.control_dir/n).exists() for n in ('CONTROLLER_STARTED.json','FAILED.json','CONTROLLER_COMPLETE.json')):
            raise ValueError('preserve prior controller attempt; never automatically repeat retirement or finance')
        write_status(args.control_dir/'CONTROLLER_STARTED.json',dict(owner=identity(psutil.Process()),production_write=False))
        try:
            while parent_alive(prepared['profile_identity']):
                if (args.profile_dir/'FAILED.json').exists():raise ValueError('bound profile failed; leave original runs waiter untouched')
                write_status(args.control_dir/'status.json',dict(state='WAITING_FOR_PROFILE_SLOT_COMPLETION',
                    profile_pid=args.profile_pid,financial_dispatch_started=False,production_write=False));time.sleep(10)
            slot=profile_complete(prepared['profile_identity'])
            write_status(args.control_dir/'PROFILE_COMPLETION_AUDIT.json',slot)
            process,manifest,_=observe_idle(args.original_wait_dir,args.original_manifest_sha256,args.waiting_pid,args.waiting_create_time)
            finance_args,proof,ready,protocol=source_context(process.cmdline(),args.original_wait_dir,manifest)
            if proof!=prepared['verification']:raise ValueError('frozen preparation context changed while waiting')
            dispatch(args,prepared,proof,ready,protocol,finance_args)
        except Exception as error:
            write_status(args.control_dir/'FAILED.json',dict(error=str(error),production_write=False));raise


if __name__=='__main__':main()
