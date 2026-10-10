#!/usr/bin/env python3
"""Read-only compare a rollback STATE_COMMIT and assigned replicas' CQ WAL.

The output is a witness for *human review*, never a license to deploy,
write to a replica, remove archives, or override the HA readiness fence.
"""
import argparse
import base64
import hashlib
import json
import mmap
from pathlib import Path
import re
import sys

NAME = re.compile(r'P[0-9]{3}\Z')
FIELD = rb'([A-Za-z0-9+/=]+)\t([A-Za-z0-9+/=]+)\t([0-9]+)\t([A-Za-z0-9+/=]+)'


def record(directory, partition, epoch, seq):
    root=Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('unsafe or unavailable journal directory')
    prefix=base64.b64encode(partition.encode('ascii'))+b'\t'+str(epoch).encode('ascii')+b'\t'+str(seq).encode('ascii')+b'\t'
    expression=re.compile(re.escape(prefix)+FIELD)
    found=[]
    for path in sorted(root.glob('*.cq4')):
        if path.is_symlink() or not path.is_file():
            raise ValueError('unsafe CQ file')
        if not path.stat().st_size:
            continue
        with path.open('rb') as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
                cursor=0
                while True:
                    offset=mapping.find(prefix,cursor)
                    if offset<0:
                        break
                    matched=expression.match(mapping,offset)
                    if not matched:
                        raise ValueError('malformed matching CQ record')
                    fields=matched.groups()
                    try:
                        et=base64.b64decode(fields[0],validate=True).decode('ascii')
                        eid=base64.b64decode(fields[1],validate=True).decode('utf8')
                        payload=base64.b64decode(fields[3],validate=True)
                    except (ValueError,UnicodeError) as exc:
                        raise ValueError('invalid CQ record encoding') from exc
                    found.append({'eventType':et,'eventId':eid,
                                  'payload':payload,'fingerprint':hashlib.sha256(matched.group()).hexdigest()})
                    cursor=matched.end()
                    if len(found)>1:
                        raise ValueError('duplicate CQ records for identical partition/epoch/seq')
    return found[0] if found else None


def inspect(root, partition, epoch, state_seq):
    if not NAME.fullmatch(partition) or epoch<=0 or state_seq<=0:
        raise ValueError('invalid partition/epoch/sequence')
    data=Path(root)
    if data.is_symlink() or not data.is_dir():
        raise ValueError('unsafe data root')
    marker_seq=state_seq+1
    archive_root=data/'OrderSvrA'/'journal'/'.archive'
    if archive_root.is_symlink() or not archive_root.is_dir():
        raise ValueError('unsafe or unavailable primary archive root')
    prefix=f'{partition}-epoch{epoch}-seq{marker_seq+1}-'
    archived=[p for p in archive_root.iterdir() if p.name.startswith(prefix)]
    if len(archived)!=1:
        raise ValueError('missing or ambiguous archived rollback segment')
    old=archived[0]
    if old.is_symlink() or not old.is_dir():
        raise ValueError('unsafe archive directory')
    state=record(old,partition,epoch,state_seq)
    marker=record(old,partition,epoch,marker_seq)
    if not state or not marker or state['eventType'] not in ('STATE_REMOVE','STATE_UPSERT') or marker['eventType']!='STATE_COMMIT':
        raise ValueError('archive lacks committed state and marker pair')
    try:
        proof=json.loads(marker['payload'])
    except (ValueError,UnicodeError) as exc:
        raise ValueError('invalid archive commit proof') from exc
    if (proof.get('version')!=1 or proof.get('stateSeq')!=state_seq or
        proof.get('stateEpoch')!=epoch or proof.get('stateEventType')!=state['eventType'] or
        proof.get('stateEventId')!=state['eventId']):
        raise ValueError('archived commit does not reference exact preceding state')
    details={}
    for node in ('OrderSvrA','OrderSvrB','OrderSvrC'):
        directory=data/node/'journal'/partition
        result={}
        for seq,label,expected in ((state_seq,'state',state),(marker_seq,'marker',marker),
                                   (marker_seq+1,'continuation',None)):
            found=record(directory,partition,epoch,seq)
            if found is None:
                result[label]={'present':False}
            else:
                row={'present':True,'eventType':found['eventType'],
                     'sha12':found['fingerprint'][:12]}
                if expected is not None:
                    row['matchesPrimaryArchive']=found['fingerprint']==expected['fingerprint']
                    if not row['matchesPrimaryArchive']:
                        raise ValueError('replica journal diverges from committed archive')
                result[label]=row
        details[node]=result
    if not (details['OrderSvrB']['state']['present'] and details['OrderSvrC']['state']['present']):
        raise ValueError('required state prefix absent from an assigned replica')
    return {
        'partition':partition,'epoch':epoch,'committedStateSeq':state_seq,
        'commitMarkerSeq':marker_seq,'sourceArchiveName':old.name,
        'primaryArchiveStateSha12':state['fingerprint'][:12],
        'primaryArchiveCommitSha12':marker['fingerprint'][:12],
        'replicas':details,
        'sameEpochRepairCandidateOnly':True,
        'canAutoApplyRepair':False,'deletionAuthorized':False,
        'reason':'Read-only CQ proof. Runtime commit watermarks, assignment authority, replica state hashes and Projection persistence NOT attested.',
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',required=True)
    p.add_argument('--partition',required=True)
    p.add_argument('--epoch',required=True,type=int)
    p.add_argument('--committed-state-seq',required=True,type=int)
    a=p.parse_args(argv)
    result=inspect(a.data_root,a.partition,a.epoch,a.committed_state_seq)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError) as exc:
        print('ORDER_ROLLBACK_WITNESS_BLOCKED '+str(exc),file=sys.stderr)
        sys.exit(2)
