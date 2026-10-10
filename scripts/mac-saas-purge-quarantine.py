#!/usr/bin/env python3
"""Safely reclaim OLD, already-staged macOS SaaS runtime after cold reinstall.

Checks immutable P246 proof, exact quarantine path, 24 healthy-new-runtime
Compose members, running Order/Trade/Robot image pins and mounts, and absence
of ANY Docker bind mounts into the old runtime. Read-only by default.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

PROOF_SHA256='41ccc17752734ed3731764de9c0ca4135452c7903e95dd47e6bf7db0ae79a707'
OLD_PATTERN=re.compile(r'dc-saas-runtime-[a-zA-Z0-9_-]+-\d{8}T\d{6}Z\Z')
NEW_PATTERN=re.compile(r'dc-saas-runtime(?:-[a-zA-Z0-9_-]+)?\Z')
EXPECTED={'ordersvr':'ghcr.io/bliplink/ordersvr:sha-7842df4',
          'ordersvr-b':'ghcr.io/bliplink/ordersvr:sha-7842df4',
          'ordersvr-c':'ghcr.io/bliplink/ordersvr:sha-7842df4',
          'tradesvr':'ghcr.io/bliplink/tradesvr:sha-e5cebdd2aa191e98a3128886634cd3b5eca6d3e6',
          'tradesvr-b':'ghcr.io/bliplink/tradesvr:sha-e5cebdd2aa191e98a3128886634cd3b5eca6d3e6',
          'robotsvr':'ghcr.io/bliplink/robotsvr:sha-5941ee6032f607a6bccc2b8da305e57f91198ad0'}
REQUIRED={'ordersvr','ordersvr-b','ordersvr-c','mysql','zookeeper','robotsvr','tradesvr','tradesvr-b','gateway','projectionsvr'}
CONFIRM='PURGE_ONLY_QUARANTINED_OLD_DC_SAAS'


def prove_paths(home,old,new,evidence):
    top=Path(home).expanduser().resolve(strict=True)/'.opentradingcore'
    if top.is_symlink() or not top.is_dir():raise ValueError('private home namespace missing or symlinked')
    qparent=top/'.dc-saas-quarantine'
    if qparent.is_symlink() or not qparent.is_dir():raise ValueError('quarantine directory unavailable or symlinked')
    oldp=Path(old).expanduser()
    if oldp.is_symlink() or not oldp.is_dir():raise ValueError('old quarantine unavailable or symlinked')
    actual=oldp.resolve(strict=True)
    if actual.parent!=qparent.resolve(strict=True) or not OLD_PATTERN.fullmatch(oldp.name):
        raise ValueError('old runtime must be an exact staged child of private quarantine')
    newp=Path(new).expanduser()
    if newp.is_symlink() or not newp.is_dir():raise ValueError('new runtime unavailable or symlinked')
    fresh=newp.resolve(strict=True)
    if fresh.parent!=top.resolve(strict=True) or not NEW_PATTERN.fullmatch(newp.name):
        raise ValueError('new runtime must be an exact private dc-saas-runtime child')
    for part in ('data','log','control','data/mysql','data/zookeeper'):
        if not (fresh/part).is_dir() or (fresh/part).is_symlink():
            raise ValueError('fresh runtime missing necessary persistent directory')
    witness=Path(evidence).expanduser()
    if witness.is_symlink() or not witness.is_file():raise ValueError('independent P246 witness unavailable')
    witness=witness.resolve(strict=True)
    if witness.parent!=top.resolve(strict=True)/'evidence'/'p246-reproducer-20261010':
        raise ValueError('independent P246 witness location is unexpected')
    if actual==fresh or actual in fresh.parents or fresh in actual.parents:
        raise ValueError('old and new runtime paths overlap')
    if actual in witness.parents or fresh in witness.parents:
        raise ValueError('P246 witness is inside a runtime')
    return actual,fresh,witness


def confirm_proof(proof):
    checksum=hashlib.sha256()
    with Path(proof).open('rb') as f:
        for blob in iter(lambda:f.read(1024*1024),b''):
            checksum.update(blob)
    if checksum.hexdigest()!=PROOF_SHA256:
        raise ValueError('P246 witness digest mismatch; refusing purge')


def docker_json(*args):
    cp=subprocess.run(['docker',*args],text=True,capture_output=True,timeout=28)
    if cp.returncode:raise ValueError('Docker state is unavailable; cannot authorize deletion')
    return json.loads(cp.stdout)


def docker_list(*args):
    cp=subprocess.run(['docker',*args],text=True,capture_output=True,timeout=20)
    if cp.returncode:raise ValueError('Docker listing failed')
    return cp.stdout.split()


def validate_running_stack(old,new):
    project=docker_list('ps','-q','--filter','label=com.docker.compose.project=dc-saas')
    if len(project)!=24 or len(set(project))!=24:raise ValueError('fresh 24-container project is incomplete')
    items=docker_json('inspect',*project)
    names={}
    for item in items:
        labels=(item.get('Config') or {}).get('Labels') or {}
        service=labels.get('com.docker.compose.service')
        if labels.get('com.docker.compose.project')!='dc-saas' or not service or service in names:
            raise ValueError('fresh project membership inconsistent')
        if item.get('State',{}).get('Running') is not True:
            raise ValueError('fresh Compose member is not running')
        names[service]=item
    if len(names)!=24 or not REQUIRED.issubset(names):raise ValueError('fresh required service topology is incomplete')
    for service,tag in EXPECTED.items():
        if names[service].get('Config',{}).get('Image')!=tag:
            raise ValueError('unreviewed image on new '+service)
    for service in ('mysql','zookeeper','ordersvr','ordersvr-c'):
        mounts=names[service].get('Mounts',[])
        if not any(m.get('Source','').startswith(str(new)+'/') for m in mounts):
            raise ValueError('fresh '+service+' is not mounted on new runtime')
    # Check **all** running or stopped Docker containers, including independent
    # docs/Playwright. Even a stopped container may retain an old bind.
    allids=docker_list('ps','-aq')
    allitems=docker_json('inspect',*allids) if allids else []
    for item in allitems:
        for m in item.get('Mounts',[]):
            source=m.get('Source','')
            if source==str(old) or source.startswith(str(old)+'/'):
                raise ValueError('old quarantine is still referenced by Docker container')
    for port in (18088,18090,18092,18094):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/'%port,timeout=5) as response:
                if response.status != 200:raise ValueError('fresh Web endpoint not healthy')
        except (OSError,ValueError) as exc:
            raise ValueError('fresh Web endpoint unavailable: '+str(port)) from exc
    return {'newComposeServices':len(names),'validatedImagePins':len(EXPECTED),
            'freshHttpHealthyPorts':[18088,18090,18092,18094],
            'independentContainersUntouched':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quarantine',required=True)
    parser.add_argument('--new-runtime',required=True)
    parser.add_argument('--evidence',required=True)
    parser.add_argument('--mode',choices=('plan','execute'),default='plan')
    parser.add_argument('--confirm',default='')
    options=parser.parse_args(argv)
    old,new,proof=prove_paths(Path.home(),options.quarantine,options.new_runtime,options.evidence)
    confirm_proof(proof)
    state=validate_running_stack(old,new)
    report={'schema':'otc-mac-saas-quarantine-purge-v1','mode':'READ_ONLY',
            'targetOldRuntime':str(old),'currentRuntime':str(new),
            'p246IndependentWitnessRetained':True,'willOnlyDeleteOldQuarantine':True,
            'oldRuntimeStillExists':True,'freshValidation':state}
    if options.mode=='execute':
        if options.confirm!=CONFIRM:raise ValueError('missing explicit quarantine purge confirmation')
        # Prevent racing any fresh installer or another purge. No stale lock
        # cleanup on behalf of another user/process.
        lock=Path(os.getenv('SAAS_AUTO_UPDATE_LOCK_FILE','/tmp/dc-saas-auto-update.lock')+'.macos')
        try:lock.mkdir(mode=0o700)
        except FileExistsError as exc:raise ValueError('Mac deploy lock is held') from exc
        try:
            # Final recheck under the same lock before irreversible deletion.
            confirm_proof(proof)
            validate_running_stack(old,new)
            if old.is_symlink() or old.parent.name!='.dc-saas-quarantine':
                raise ValueError('quarantine path changed')
            shutil.rmtree(old)
            report['mode']='PERMANENTLY_PURGED_OLD_ONLY'
            report['oldRuntimeStillExists']=False
        finally:
            lock.rmdir()
    print(json.dumps(report,indent=2))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print('MAC_SAAS_OLD_PURGE_DENIED: '+str(exc)[:210],file=sys.stderr)
        sys.exit(2)
