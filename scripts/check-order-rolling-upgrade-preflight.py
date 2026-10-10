#!/usr/bin/env python3
"""Read-only, fail-closed OrderSvr rolling-upgrade risk preflight.

Never authorizes a container restart, ZK reassignment or WAL mutation.
Even GREEN static snapshots cannot replace an atomic writer drain,
committed replica attestation, and authoritative Projection watermarks.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

NODES = {'OrderSvrA': 'dc-saas-ordersvr', 'OrderSvrB': 'dc-saas-ordersvr-b',
         'OrderSvrC': 'dc-saas-ordersvr-c'}
PARTITIONS = 256
ZK_PATTERN = re.compile(r'\{[^{}]*"partitionId"[^{}]*\}')
FAILURE_PATTERN = re.compile(r'ORDER_PARTITION_RECOVERY_FAILED|PARTITION_NOT_READY|replica catch-up made no progress')
MANDATORY_CONFIG = {'order.cluster.replication.consistencyMode': 'SYNC_PER_RECORD',
                    'order.cluster.replication.required': 'true',
                    'order.cluster.failover.minimumLiveSynchronizedReplicas': '2'}


def command(args, input_text=None, timeout=30):
    cp = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=timeout)
    if cp.returncode:
        raise ValueError('read-only prerequisite command failed: '+args[0]+' '+args[1])
    return cp.stdout + '\n' + cp.stderr


def decode_assignments(text):
    rows=[]
    for line in text.splitlines():
        raw=line.strip()
        if raw.startswith('{') and '"partitionId"' in raw:
            try:
                value=json.loads(raw)
            except ValueError as exc:
                raise ValueError('invalid ZooKeeper JSON assignment') from exc
            if not isinstance(value,dict):
                raise ValueError('invalid ZooKeeper assignment')
            rows.append(value)
    if not rows:
        # The ZK CLI includes terminal prefixes and unrelated log messages.
        for encoded in ZK_PATTERN.findall(text):
            try: rows.append(json.loads(encoded))
            except ValueError as exc: raise ValueError('invalid ZooKeeper JSON assignment') from exc
    ids=[v.get('partitionId') for v in rows]
    expected={'P%03d'%i for i in range(PARTITIONS)}
    if len(rows)!=PARTITIONS or len(set(ids))!=PARTITIONS or set(ids)!=expected:
        raise ValueError('missing, duplicate or unexpected partition assignment')
    return sorted(rows,key=lambda row:row['partitionId'])


def read_config(filename):
    p=Path(filename)
    if p.is_symlink() or not p.is_file():
        raise ValueError('missing or unsafe OrderSvr configuration')
    data={}
    for line in p.read_text(encoding='utf8').splitlines():
        line=line.strip()
        if not line or line.startswith(('#','!')) or '=' not in line: continue
        name,value=line.split('=',1)
        if name.strip().startswith('order.cluster.'):
            data[name.strip()]=value.strip()
    return data


def assignment_issues(rows):
    errors=[];primaries=collections.Counter();not_ready=[]
    for row in rows:
        part=row['partitionId'];primary=row.get('primary')
        replicas=row.get('replicas') or ([row['replica']] if row.get('replica') else [])
        epoch=row.get('epoch');state=row.get('state')
        if primary not in NODES or not isinstance(replicas,list) or len(replicas)<2 or (
            any(n not in NODES for n in replicas) or len(set(replicas))!=len(replicas)
            or primary in replicas):
            errors.append('INVALID_REPLICA_TOPOLOGY:'+part)
        else:
            primaries[primary]+=1
        if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<1:
            errors.append('INVALID_EPOCH:'+part)
        if state!='READY':not_ready.append(part)
    if not_ready: errors.append('ZOOKEEPER_ASSIGNMENTS_NOT_READY:'+','.join(not_ready[:8]))
    return errors,dict(sorted(primaries.items()))


def compare_snapshots(rows,data_root):
    root=Path(data_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('unsafe or missing OrderSvr data root')
    mismatches=[];missing=[];snapshot_count=0
    for row in rows:
        part=row['partitionId'];digests=[]
        for node in NODES:
            path=root/node/'snapshot'/part/'snapshot.json'
            if path.is_symlink() or not path.is_file():
                missing.append(f'{part}:{node}');continue
            try:raw=path.read_bytes();val=json.loads(raw)
            except (OSError,ValueError) as exc:raise ValueError('unreadable snapshot '+part) from exc
            if val.get('partitionId')!=part or val.get('epoch')!=row['epoch']:
                mismatches.append(part)
            canonical=json.dumps(val,sort_keys=True,separators=(',',':')).encode()
            digests.append(hashlib.sha256(canonical).digest())
            snapshot_count+=1
        if len(digests)==len(NODES) and len(set(digests))>1:mismatches.append(part)
    return {'snapshotFilesInspected':snapshot_count,
            'missingSnapshotPartitions':sorted(set(x.split(':')[0] for x in missing)),
            'divergentPartitions':sorted(set(mismatches)),
            'totalPartitions':len(rows)}


def evaluate(rows,configs,snapshots,images,log_failure_count,used_percent):
    blockers=[]
    issues,primary_counts=assignment_issues(rows)
    blockers+=issues
    for node in NODES:
        config=configs.get(node)
        if config is None:
            blockers.append('MISSING_CONFIG:'+node);continue
        for field,expected in MANDATORY_CONFIG.items():
            if config.get(field)!=expected:
                blockers.append('UNEXPECTED_SYNC_POLICY:'+node+':'+field)
        if config.get('order.cluster.replication.archivedCommitRepairEnabled','false')!='false':
            blockers.append('ARCHIVE_REPAIR_ALREADY_ENABLED:'+node)
    if snapshots['divergentPartitions']:
        blockers.append('SNAPSHOT_MISMATCH:'+','.join(snapshots['divergentPartitions'][:12]))
    if snapshots['missingSnapshotPartitions']:
        blockers.append('MISSING_SNAPSHOTS:'+','.join(snapshots['missingSnapshotPartitions'][:12]))
    for node in NODES:
        if not images.get(node,{}).get('running'):
            blockers.append('NODE_NOT_RUNNING:'+node)
        if not images.get(node,{}).get('image'):
            blockers.append('NODE_IMAGE_UNKNOWN:'+node)
    if log_failure_count is None:
        blockers.append('RECENT_RUNTIME_RECOVERY_LOGS_UNAVAILABLE')
    elif log_failure_count>0:
        blockers.append('ACTIVE_RECOVERY_ERRORS:'+str(log_failure_count))
    if used_percent is None:
        blockers.append('DISK_HEADROOM_UNKNOWN')
    elif used_percent>=80:
        blockers.append('DISK_PRESSURE:'+str(round(used_percent,1))+'%')
    # This tool is intentionally NOT the write drain or runtime-attestation protocol.
    blockers += ['WRITE_DRAIN_NOT_ATTESTED', 'LIVE_DURABLE_REPLICA_WATERMARKS_NOT_ATTESTED',
                 'PROJECTION_WATERMARKS_NOT_ATTESTED','RESTART_ROLLBACK_PLAN_NOT_ATTESTED']
    return {'schema':'otc-order-upgrade-preflight-v1','readOnly':True,
            'canRestartOrderNodes':False,'canEnableP246Repair':False,
            'decision':'BLOCKED', 'blockers':list(dict.fromkeys(blockers)),
            'primaryCounts':{k:primary_counts.get(k,0) for k in NODES},
            'zkReadyAssignments':sum(r.get('state')=='READY' for r in rows),
            'assignedPartitions':len(rows),'snapshots':snapshots,
            'recentRecoveryErrorLines':log_failure_count,'diskUsedPercent':used_percent,
            'images':{k:dict(images.get(k,{})) for k in NODES},
            'notice':'Coordination READY is not runtime READY; static snapshots are not durable commit attestation.'}


def collect():
    commands=''.join(f'get /dc/cluster/ordersvr/partitions/P{i:03d}\n' for i in range(PARTITIONS))+'quit\n'
    zk=command(['docker','exec','-i','dc-saas-zookeeper','zkCli.sh','-server','127.0.0.1:32181'],commands,timeout=45)
    rows=decode_assignments(zk)
    info=json.JSONDecoder().raw_decode(command(['docker','inspect']+list(NODES.values()),timeout=20).lstrip())[0]
    by_name={x['Name'].lstrip('/'):x for x in info}
    images={}
    configs={}
    data_root=None
    for node,container in NODES.items():
        item=by_name.get(container)
        if item is None: raise ValueError('unavailable Docker node metadata '+node)
        images[node]={'running':bool(item.get('State',{}).get('Running')),
                      'image':item.get('Config',{}).get('Image')}
        mounts=item.get('Mounts') or []
        config_mount=next((m for m in mounts if m.get('Destination')=='/srv/dc/dc/OrderSvr/config/application.properties'),None)
        data_mount=next((m for m in mounts if m.get('Destination')=='/srv/dc/data'),None)
        if not config_mount or not data_mount:raise ValueError('required config/data mount missing')
        configs[node]=read_config(config_mount['Source'])
        if data_root is None:data_root=data_mount['Source']
        elif data_root!=data_mount['Source']:raise ValueError('nodes do not share expected data root')
    snapshots=compare_snapshots(rows,data_root)
    combined=0
    for container in NODES.values():
        logs=command(['docker','logs','--since','60s',container],timeout=15)
        combined += sum(bool(FAILURE_PATTERN.search(line)) for line in logs.splitlines())
    usage=shutil.disk_usage(data_root)
    disk_percent=round((usage.total-usage.free)*100/usage.total,2)
    return rows,configs,snapshots,images,combined,disk_percent,data_root


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='write report outside runtime data root; optional')
    opts=parser.parse_args(argv)
    rows,configs,snapshots,images,errors,disk,data_root=collect()
    result=evaluate(rows,configs,snapshots,images,errors,disk)
    result['checkedAtUtc']=datetime.now(timezone.utc).isoformat()
    if opts.output:
        original_out=Path(opts.output)
        if original_out.is_symlink():
            raise ValueError('preflight report output must not be a symlink')
        out=original_out.resolve(strict=False)
        runtime=Path(data_root).resolve()
        if out==runtime or runtime in out.parents:
            raise ValueError('preflight report output must be outside OrderSvr runtime data')
        if out.is_symlink() or out.exists():raise ValueError('report output exists or is symlink')
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open('x',encoding='utf8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
    # Return non-zero on BLOCKED: usable as a release guard, not a green metric.
    return 2

if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError,subprocess.TimeoutExpired,KeyError) as exc:
        print('ORDER_UPGRADE_PREFLIGHT_UNAVAILABLE: '+type(exc).__name__+': '+str(exc)[:130],file=sys.stderr)
        sys.exit(3)
