#!/usr/bin/env python3
"""Never used while Replica A is running; offline physically durable atomic install.

Live B stays untouched. Exact 10 snapshot source commit identities were
independently proven in A/B read-only Chronicle and current ZK assignments.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--apply',action='store_true')
p.add_argument('--rollback',action='store_true')
p.add_argument('--stage',default=None,help='pre-sealed Snapshot and rollback directory')
args=p.parse_args()
assert not (args.apply and args.rollback)
home=pathlib.Path.home()
base=home/'.opentradingcore/dc-saas-runtime-zkfix-20261011/data'
artifacts=home/'.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts'
stage=pathlib.Path(args.stage) if args.stage else artifacts/'trade-a-offline-warm-20261012'
if stage.parent != artifacts or stage.is_symlink() or not stage.is_dir():
    raise RuntimeError('unsafe offline Trade-A Snapshot staging directory')
rows=json.loads((stage/'manifest.json').read_text())['partitions']
assert len(rows)==10
def sha(path):
    hasher=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            hasher.update(chunk)
    return hasher.hexdigest()
def safe_file(file):
    if file.is_symlink() or not file.is_file():raise RuntimeError('unsafe Snapshot source '+str(file))
def status(name):
    return subprocess.check_output(['docker','inspect','-f','{{.State.Running}}',name],
                                   text=True).strip()=='true'
for row in rows:
    part=row['partition']
    source=stage/'new'/f'{part}.json'
    rollback=stage/'rollback'/f'{part}.json'
    safe_file(source);safe_file(rollback)
    if sha(source)!=row['sha256'] or sha(rollback)!=row['rollbackSha256']:
        raise RuntimeError('staged or rollback hash mismatch '+part)
if args.apply or args.rollback:
    if status('dc-saas-tradesvr'):
        raise RuntimeError('refuse live Trade-A snapshot mutation: STOP REPLICA A FIRST')
    if not status('dc-saas-tradesvr-b'):
        raise RuntimeError('Trade-B primary absent: no changes permitted')
previous=[]
def replace_verified(source,dest,expected):
    fd,temp=tempfile.mkstemp(prefix='.verified-replica-offline-',suffix='.part',dir=str(dest.parent))
    try:
        with os.fdopen(fd,'wb') as out,open(source,'rb') as inp:
            shutil.copyfileobj(inp,out,1024*1024)
            out.flush();os.fsync(out.fileno())
        if sha(temp)!=expected:raise RuntimeError('temporary file hash differs')
        os.replace(temp,dest)
        directory=os.open(str(dest.parent),os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        if sha(dest)!=expected:raise RuntimeError('installed image SHA mismatch')
    finally:
        if os.path.exists(temp):os.unlink(temp)
try:
    for row in rows:
        part=row['partition']
        dest=base/'TradeSvrA/snapshot'/part/'latest.json'
        safe_file(dest)
        if args.apply:
            if sha(dest)!=row['rollbackSha256']:
                raise RuntimeError('unexpected original full Snapshot changed '+part)
            selected=stage/'new'/f'{part}.json'
            expected=row['sha256']
        elif args.rollback:
            if sha(dest) not in (row['sha256'],row['rollbackSha256']):
                raise RuntimeError('Replica image changed since warm install '+part)
            selected=stage/'rollback'/f'{part}.json'
            expected=row['rollbackSha256']
        else:
            print('DRY_RUN_REPLICA_IMAGE',part,'old=',sha(dest)[:12],
                  'expected-new=',row['sha256'][:12]);continue
        replace_verified(selected,dest,expected)
        previous.append(row)
        print('REPLICA_OFFLINE_ATOMIC_IMAGE',part,'seq='+str(row['snapshotSeq']),
              'action='+('rollback' if args.rollback else 'warm'),flush=True)
except BaseException:
    if args.apply:
        print('INSTALL_EXCEPTION_ROLLING_BACK_PARTIAL_IMAGES',flush=True)
        for row in reversed(previous):
            replace_verified(stage/'rollback'/f"{row['partition']}.json",
                base/'TradeSvrA/snapshot'/row['partition']/'latest.json',
                row['rollbackSha256'])
    raise
print('REPLICA_IMAGE_VERIFIED',len(rows),flush=True)
