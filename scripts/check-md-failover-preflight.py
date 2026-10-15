#!/usr/bin/env python3
"""Read-only MD promotion preflight; never promotes/changes ZK or restarts nodes.

MD is a derived-state service: one live assigned replica/learner may rebuild
from the authoritative Order subscribeWithImage snapshot, without MD-to-MD
WAL replication or two synchronized copies. Fail closed until old-publisher
fencing and a complete fresh Order image can independently be proven.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
import re
import shutil
from pathlib import Path
import subprocess
import sys

NODES={'MDSvrA':'dc-saas-mdsvr','MDSvrB':'dc-saas-mdsvr-b','MDSvrC':'dc-saas-mdsvr-c'}
COUNT=256
REQUIRED_IMAGE='ghcr.io/bliplink/mdsvr:sha-48544e5'
# Host VM and snapshot/archive storage must have a free-space reserve.
# This check runs ONLY during explicit read-only HA preflight.
MIN_HOST_FREE_BYTES=5*1024*1024*1024
# Reviewed ARM64 MD-C canary, from successful MD CI #38419947005.
# ARM64 manifest: sha256:3f02b5359dbc17e9123ac0cec49f2f98225bff5ce87d295548dac5cd0452abf3
# A known tag is never sufficient: also pin the Docker config ID and source
# revision verified from the fetched GHCR image.
REVIEWED_GHCR_IMAGES = {
    'ghcr.io/bliplink/mdsvr:sha-026306b': {
        'configImageId':'sha256:5ae7d0479d6cb335dc24dfc3f65947b13733fe99b9e28587835dff87a07c4c3a',
        'imageRevision':'026306b1b311c41bff12c9296cef667e681a7688',
        'commonGav':'io.github.bliplink:com.app.common:3.0.19',
    }
}

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

def parse_ephemeral_membership(zk_output):
    """Require the exact physical-server ephemeral znode, not a static parent.

    Unknown or unparseable members are absent; never infer node liveness from
    Docker health or from a stale READY partition assignment.
    """
    found={name:False for name in NODES}
    seen=set()
    member=None
    for raw in zk_output.splitlines():
        line=raw.strip()
        request=re.search(r'\bget -s /MDTService/(MDSvr[A-C])/\1(?:\s|$)',line)
        if request:
            member=request.group(1)
            seen.add(member)
            found[member]=False
            continue
        if member and line.startswith('ephemeralOwner = '):
            raw_owner=line.split('=',1)[1].strip()
            found[member]=bool(re.fullmatch(r'0x[0-9a-fA-F]+',raw_owner)
                               and int(raw_owner,16)>0)
            member=None
        elif member and ('KeeperErrorCode' in line or 'Node does not exist' in line):
            member=None
    return {name:found[name] and name in seen for name in NODES}


def evaluate(rows,images,members=None,required_image=REQUIRED_IMAGE,per_node_images=None,host_free_bytes=None):
    # Explicitly locked local Mac images may be reviewed without pretending
    # they are the old GHCR image. This NEVER grants failover authority.
    def immutable_id(value):
        return bool(re.fullmatch(r'sha256:[0-9a-f]{64}', value or ''))

    def valid_lock(value):
        return immutable_id(value) or value==REQUIRED_IMAGE or value in REVIEWED_GHCR_IMAGES or bool(re.fullmatch(
            r'dc-saas/mdsvr:cluster-dev-local-[a-zA-Z0-9_.-]+',value or ''))
    if not valid_lock(required_image):
        raise ValueError('MD expected image must be an explicitly locked, reviewed image')
    per_node_images = {} if per_node_images is None else per_node_images
    if not isinstance(per_node_images,dict) or any(
            node not in NODES or not valid_lock(value)
            for node,value in per_node_images.items()):
        raise ValueError('MD per-node image locks must be reviewed, immutable and known')
    if host_free_bytes is not None and (not isinstance(host_free_bytes,int) or host_free_bytes<0):
        raise ValueError('invalid host disk free-space reading')
    reasons=[];primaries=Counter();single=[];without_candidate=[];wrong=[];unready=[]
    if host_free_bytes is not None and host_free_bytes<MIN_HOST_FREE_BYTES:
        reasons.append('HOST_DISK_RESERVE_BELOW_5G')
    members=members or {}
    if len(rows)!=COUNT: raise ValueError('incomplete MD topology')
    for row in rows:
        part=row['partitionId'];primary=row.get('primary')
        replicas=row.get('replicas')
        if replicas is None or len(replicas)==0: replicas=[row.get('replica')] if row.get('replica') else []
        if not isinstance(replicas,list):replicas=[]
        learners=row.get('learners') or []
        if not isinstance(learners,list):learners=[]
        if primary in NODES:primaries[primary]+=1
        if (primary not in NODES or any(n not in NODES for n in replicas+learners)
            or primary in replicas+learners or len(set(replicas+learners))!=len(replicas+learners)):
            wrong.append(part)
        if len(replicas)<2:single.append(part)
        if not (replicas or learners): without_candidate.append(part)
        if row.get('state')!='READY' or not isinstance(row.get('epoch'),int) or row.get('epoch',0)<1:
            unready.append(part)
    if wrong:reasons.append('INVALID_MD_NODE_PLACEMENT:'+','.join(wrong[:5]))
    if without_candidate:reasons.append('MD_NO_ASSIGNED_RECOVERY_CANDIDATE:'+str(len(without_candidate))+'/'+str(COUNT))
    if unready:reasons.append('MD_ASSIGNMENTS_NOT_READY:'+','.join(unready[:5]))
    for node,container in NODES.items():
        detail=images.get(node,{})
        expected=per_node_images.get(node,required_image)
        trusted=REVIEWED_GHCR_IMAGES.get(expected)
        image_matches = (detail.get('configImageId') == expected
                         if immutable_id(expected)
                         else detail.get('image') == expected)
        if (not image_matches or not detail.get('running')
                or (trusted is not None and any(
                    detail.get(field)!=value for field,value in trusted.items()))):
            reasons.append('MD_NODE_UNHEALTHY_OR_UNREVIEWED:'+node)
        if members.get(node) is not True:
            reasons.append('MD_EPHEMERAL_MEMBER_NOT_ATTESTED:'+node)
    # These cannot be asserted by ZooKeeper READY or a live snapshot count.
    reasons.extend(['ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',
                    'MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED',
                    'MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED',
                    # MD PR #8 separately requires locally applied Image +
                    # contiguous Diff proof bound to elected owner/epoch.
                    'MD_CANDIDATE_APPLIED_IMAGE_DIFF_UNATTESTED',
                    'MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED',
                    'ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED'])
    return {'schema':'otc-md-failover-preflight-v1','readOnly':True,
            'hostDiskFreeBytes':host_free_bytes,'hostDiskRequiredFreeBytes':MIN_HOST_FREE_BYTES,
            'expectedImage':required_image,'expectedImagesByNode':{
                node:per_node_images.get(node,required_image) for node in NODES},
            'canInjectMdPrimaryFault':False,'canPromote':False,
            'decision':'BLOCKED','blockers':reasons,
            'partitionCount':len(rows),'primaryCounts':dict(sorted(primaries.items())),
            'singleReplicaPartitionCount':len(single),'withoutRecoveryCandidateCount':len(without_candidate),
            'unreadyPartitions':len(unready),
            'images':images,'ephemeralMembers':members,
            'notice':'MD need not replicate its own WAL; a live assigned standby alone cannot prove old-owner fencing or a fresh full Order image.'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='create JSON report, outside live data; never overwrite')
    parser.add_argument('--expected-image',default=REQUIRED_IMAGE,
                        help='explicitly reviewed GHCR/local immutable image tag; does NOT enable failover')
    parser.add_argument('--expected-md-c-image',
                        help='explicitly locked MD-C canary image; other MD nodes retain --expected-image')
    options=parser.parse_args(argv)
    instructions=''.join('get /dc/cluster/mdsvr/partitions/P%03d\n'%p for p in range(COUNT))
    instructions+=''.join('get -s /MDTService/{0}/{0}\n'.format(n) for n in NODES)+'quit\n'
    zk_read=command(['docker','exec','-i','dc-saas-zookeeper','zkCli.sh','-server','127.0.0.1:32181'],instructions,timeout=65)
    rows=parse_assignments(zk_read)
    members=parse_ephemeral_membership(zk_read)
    states=json.loads(command(['docker','inspect']+list(NODES.values()),timeout=25))
    by_name={x['Name'].lstrip('/'):x for x in states}
    images={}
    for node,container in NODES.items():
        item=by_name.get(container)
        if not item:raise ValueError('missing node metadata: '+node)
        config=item.get('Config',{})
        labels=config.get('Labels') or {}
        images[node]={'running':item.get('State',{}).get('Running') is True,
                      'image':config.get('Image'),
                      'configImageId':item.get('Image'),
                      'imageRevision':labels.get('org.opencontainers.image.revision'),
                      'commonGav':labels.get('dc.common.gav')}
    locks={'MDSvrC':options.expected_md_c_image} if options.expected_md_c_image else None
    # The host path is mounted from the same APFS Data volume backing Colima.
    # No writes, network calls or Docker changes occur during this check.
    free_bytes=shutil.disk_usage(str(Path.home())).free
    report=evaluate(rows,images,members,options.expected_image,locks,
                    host_free_bytes=free_bytes)
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
