#!/usr/bin/env python3
"""Read-only MD promotion preflight; never promotes/changes ZK or restarts nodes.

Two assigned replicas are required for the current generic common
PartitionFailoverController to promote while keeping a live replica. Even that
replica topology cannot prove a synchronized market-data state; require
independent freshness and fencing proof before implementing a writer.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys

NODES={'MDSvrA':'dc-saas-mdsvr','MDSvrB':'dc-saas-mdsvr-b','MDSvrC':'dc-saas-mdsvr-c'}
COUNT=256
REQUIRED_IMAGE='ghcr.io/bliplink/mdsvr:sha-48544e5'

def command(args,input=None,timeout=45):
    result=subprocess.run(args,input=input,text=True,capture_output=True,timeout=timeout)
    if result.returncode:raise ValueError('required read-only lookup unavailable: '+args[0])
    return result.stdout

def parse_assignments(text):
    rows=[]
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('{') and '"partitionId"' in line:
            try:rows.append(json.loads(line))
            except ValueError as err:raise ValueError('invalid ZooKeeper assignment') from err
    expected={'P%03d'%i for i in range(COUNT)}
    ids=[row.get('partitionId') for row in rows]
    if len(rows)!=COUNT or set(ids)!=expected or len(set(ids))!=COUNT:
        raise ValueError('incomplete/duplicate/unknown MD assignments')
    return sorted(rows,key=lambda x:x['partitionId'])

def evaluate(rows,images):
    reasons=[];primaries=Counter();single=[];wrong=[];unready=[]
    if len(rows)!=COUNT: raise ValueError('incomplete MD topology')
    for row in rows:
        part=row['partitionId'];primary=row.get('primary')
        replicas=row.get('replicas')
        if replicas is None or len(replicas)==0: replicas=[row.get('replica')] if row.get('replica') else []
        if not isinstance(replicas,list):replicas=[]
        if primary in NODES:primaries[primary]+=1
        if primary not in NODES or any(n not in NODES for n in replicas) or primary in replicas or len(set(replicas))!=len(replicas):
            wrong.append(part)
        if len(replicas)<2:single.append(part)
        if row.get('state')!='READY' or not isinstance(row.get('epoch'),int) or row.get('epoch',0)<1:
            unready.append(part)
    if wrong:reasons.append('INVALID_MD_NODE_PLACEMENT:'+','.join(wrong[:5]))
    if single:reasons.append('INSUFFICIENT_LIVE_SYNCHRONIZED_REPLICA_SLOTS:'+str(len(single))+'/'+str(COUNT))
    if unready:reasons.append('MD_ASSIGNMENTS_NOT_READY:'+','.join(unready[:5]))
    for node,container in NODES.items():
        detail=images.get(node,{})
        if detail.get('image')!=REQUIRED_IMAGE or not detail.get('running'):
            reasons.append('MD_NODE_UNHEALTHY_OR_UNREVIEWED:'+node)
    # These cannot be asserted by ZooKeeper READY or a live snapshot count.
    reasons.extend(['MD_DURABLE_SOURCE_WATERMARK_PROOFS_MISSING',
                    'MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED',
                    'MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED',
                    'ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED'])
    return {'schema':'otc-md-failover-preflight-v1','readOnly':True,
            'canInjectMdPrimaryFault':False,'canPromote':False,
            'decision':'BLOCKED','blockers':reasons,
            'partitionCount':len(rows),'primaryCounts':dict(sorted(primaries.items())),
            'singleReplicaPartitionCount':len(single),'unreadyPartitions':len(unready),
            'images':images,
            'notice':'A READY ZK assignment and a visible replica do not attest a durable complete market image or fencing.'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='create JSON report, outside live data; never overwrite')
    options=parser.parse_args(argv)
    instructions=''.join('get /dc/cluster/mdsvr/partitions/P%03d\n'%p for p in range(COUNT))+'quit\n'
    rows=parse_assignments(command(['docker','exec','-i','dc-saas-zookeeper','zkCli.sh','-server','127.0.0.1:32181'],instructions,timeout=65))
    states=json.loads(command(['docker','inspect']+list(NODES.values()),timeout=25))
    by_name={x['Name'].lstrip('/'):x for x in states}
    images={}
    for node,container in NODES.items():
        item=by_name.get(container)
        if not item:raise ValueError('missing node metadata: '+node)
        images[node]={'running':item.get('State',{}).get('Running') is True,
                      'image':item.get('Config',{}).get('Image')}
    report=evaluate(rows,images)
    report['checkedAtUtc']=datetime.now(timezone.utc).isoformat()
    if options.output:
        dest=Path(options.output).expanduser()
        if dest.is_symlink() or dest.exists():raise ValueError('output already exists or is a symlink')
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('x',encoding='utf8') as handle:json.dump(report,handle,indent=2)
    print(json.dumps(report,indent=2))
    return 2 # Never greenlight live MD primary SIGKILL from only this preflight.
if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:
        print('MD_FAILOVER_PREFLIGHT_UNAVAILABLE: '+type(error).__name__+': '+str(error)[:115],file=sys.stderr)
        sys.exit(3)
