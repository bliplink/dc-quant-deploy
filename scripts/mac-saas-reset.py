#!/usr/bin/env python3
"""Mac/Colima demo reset: default read-only plan; explicit fenced staging only.

This is not the order protocol's HA drain. Do not use it for live migration.
It safely stages one disposable Compose project's old runtime for a *cold*
clean install. Never automatically purge the quarantine or unrelated Docker.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PROJECT = 'dc-saas'
PROOF_SHA256 = '41ccc17752734ed3731764de9c0ca4135452c7903e95dd47e6bf7db0ae79a707'
PROOF_FILE = 'P246-primary-archived-commit.tar.gz'
RESET_CONFIRM = 'STAGE_DISPOSABLE_DC_SAAS'
ROOT_PATTERN = re.compile(r'dc-saas-runtime(?:-[a-zA-Z0-9_-]+)?\Z')
SERVICE_NAMES = {'ordersvr','ordersvr-b','ordersvr-c','mysql','zookeeper','gateway','tradesvr','tradesvr-b','projectionsvr','robotsvr'}


def safe_roots(home, root, evidence):
    home = Path(home).expanduser().resolve(strict=True)
    top = home / '.opentradingcore'
    if top.is_symlink() or not top.is_dir():
        raise ValueError('missing or symlinked private .opentradingcore root')
    source = Path(root).expanduser()
    if source.is_symlink() or not source.is_dir():
        raise ValueError('runtime root unavailable or symlinked')
    resolved = source.resolve(strict=True)
    if resolved.parent != top.resolve(strict=True) or not ROOT_PATTERN.fullmatch(source.name):
        raise ValueError('runtime root must be an immediate dc-saas-runtime-* child of ~/.opentradingcore')
    for child in ('data','log','control'):
        if not (resolved / child).is_dir() or (resolved / child).is_symlink():
            raise ValueError('runtime root missing required data/log/control layout')
    proof = Path(evidence).expanduser()
    if proof.is_symlink() or not proof.is_file():
        raise ValueError('P246 witness must be a regular non-symlink file')
    proof_resolved = proof.resolve(strict=True)
    if resolved == proof_resolved or resolved in proof_resolved.parents:
        raise ValueError('P246 witness must be outside disposable runtime root')
    # Evidence MUST be physically under a sibling private evidence directory.
    if proof_resolved.parent != top.resolve(strict=True) / 'evidence' / 'p246-reproducer-20261010':
        raise ValueError('P246 evidence directory does not match expected private namespace')
    return resolved, proof_resolved, top


def verify_evidence(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if digest.hexdigest() != PROOF_SHA256:
        raise ValueError('P246 evidence SHA-256 mismatch; reset denied')
    return digest.hexdigest()


def docker(*args, stdin=None):
    command = ['docker', *args]
    done = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=90)
    if done.returncode:
        raise ValueError('Docker prerequisite failed: '+command[1])
    return done.stdout


def discover_project(root):
    rows = docker('ps','-aq','--filter','label=com.docker.compose.project='+PROJECT).split()
    if not rows:
        raise ValueError('no running/exited Compose project containers: refusing ambiguous reset')
    if len(rows) > 45 or len(set(rows)) != len(rows):
        raise ValueError('unexpected number or duplicate Docker IDs')
    members = json.loads(docker('inspect',*rows))
    if len(members) != len(rows):
        raise ValueError('Docker inspect returned incomplete project membership')
    names = set()
    root_bound = set()
    for item in members:
        name = item.get('Name','').lstrip('/')
        labels = (item.get('Config') or {}).get('Labels') or {}
        service = labels.get('com.docker.compose.service')
        if not name.startswith('dc-saas-') or labels.get('com.docker.compose.project') != PROJECT:
            raise ValueError('unexpected non-dc-saas container in project')
        if not service or service in names:
            raise ValueError('duplicate or missing Compose service in project')
        names.add(service)
        binds = [m.get('Source','') for m in item.get('Mounts',[]) if m.get('Type') == 'bind']
        if any(p == str(root) or p.startswith(str(root) + '/') for p in binds):
            root_bound.add(service)
    if not SERVICE_NAMES.issubset(names):
        raise ValueError('required full-HA Compose services missing: '+','.join(sorted(SERVICE_NAMES-names)))
    if not {'ordersvr','ordersvr-c','mysql','zookeeper'}.issubset(root_bound):
        raise ValueError('runtime bind mounts do not match expected A/C/MySQL/ZK ownership')
    # Foreign containers sharing the old runtime are a separate hard stop.
    allids = docker('ps','-aq').split()
    external = sorted(set(allids) - set(rows))
    test_runner = []
    if external:
        inspected = json.loads(docker('inspect',*external))
        for item in inspected:
            mounts = item.get('Mounts',[])
            shared = [m for m in mounts if m.get('Source','') == str(root)
                      or m.get('Source','').startswith(str(root) + '/')]
            if not shared:
                continue
            # A single known disposable Playwright runner is the only allowed
            # non-Compose sidecar. It must not own DB/Order state or other
            # mounts from the runtime. Do not extend this exception by prefix.
            if (item.get('Name') == '/dc-saas-web-e2e-runner'
                and (item.get('Config') or {}).get('Image') == 'mcr.microsoft.com/playwright:v1.55.0-noble'
                and len(shared) == 1
                and shared[0].get('Source') == str(root / 'e2e-artifacts')
                and shared[0].get('Destination') == '/artifacts'
                and not test_runner):
                test_runner.append(item['Id'])
                continue
            raise ValueError('runtime is shared with an unknown non-project Docker container')
    return sorted(rows), sorted(names), sorted(test_runner)


def build_plan(root, evidence_sha, ids, services, quarantine, test_runner=()):
    return {'schema':'otc-macos-cold-reset-v1', 'project':PROJECT,
            'mode':'READ_ONLY', 'serviceCount':len(services), 'services':services,
            'containerCount':len(ids), 'disposableTestRunnerCount':len(test_runner),
            'root':str(root), 'quarantineRoot':str(quarantine),
            'evidenceSha256':evidence_sha, 'evidenceRetained':True,
            'scope':'ONLY containers with com.docker.compose.project=dc-saas and ONE verified runtime directory',
            'independentApiDocsRetained':True,'oldDataPurged':False,
            'requiresColdDowntime':True, 'actionsIfStaged':['stop exact Compose project members','stop exact verified Playwright runner (if present)','remove exact Compose project members and verified runner','atomically move disposable runtime into private quarantine'],
            'next':'Run ./deploy-saas-macos.sh --full-cluster with a NEW Mac runtime root; verify before deciding whether to remove quarantined old data.'}


def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root',required=True)
    parser.add_argument('--evidence',required=True)
    parser.add_argument('--mode',choices=('plan','stage'),default='plan')
    parser.add_argument('--confirm',default='')
    opts=parser.parse_args(argv)
    root, proof, top=safe_roots(Path.home(),opts.runtime_root,opts.evidence)
    evidence_sha=verify_evidence(proof)
    quarantine_parent=top/'.dc-saas-quarantine'
    now=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    quarantine=quarantine_parent/(root.name+'-'+now)
    # An unattended inspection must never create directories or lock files.
    if opts.mode=='stage':
        if opts.confirm!=RESET_CONFIRM:
            raise ValueError('cold reset requires the exact explicit confirmation token')
        lock=Path(os.getenv('SAAS_AUTO_UPDATE_LOCK_FILE','/tmp/dc-saas-auto-update.lock')+'.macos')
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise ValueError('existing Mac deploy lock; refusing concurrent reset') from exc
        try:
            return stage(root,proof,evidence_sha,quarantine_parent,quarantine)
        finally:
            lock.rmdir()
    ids,services,runner=discover_project(root)
    print(json.dumps(build_plan(root,evidence_sha,ids,services,quarantine,runner),indent=2))
    return 0


def stage(root, proof, evidence_sha, quarantine_parent, quarantine):
    ids,services,runner=discover_project(root)
    plan=build_plan(root,evidence_sha,ids,services,quarantine,runner)
    if quarantine_parent.is_symlink():
        raise ValueError('unsafe symlinked quarantine directory')
    quarantine_parent.mkdir(mode=0o700,exist_ok=True)
    if quarantine.exists():
        raise ValueError('quarantine name already occupied')
    # Recheck Docker project membership before any destructive command.
    verify_ids,verify_services,verify_runner=discover_project(root)
    if ids != verify_ids or services != verify_services or runner != verify_runner:
        raise ValueError('container membership changed during preflight')
    if runner:
        docker('stop','-t','30',*runner)
    docker('stop','-t','30',*ids)
    # No container may remain running when its persistent data is moved.
    stopped=json.loads(docker('inspect',*ids))
    if any(x.get('State',{}).get('Running') for x in stopped):
        raise ValueError('project container still running after Docker stop')
    if runner:
        docker('rm',*runner)
    docker('rm',*ids)
    os.rename(root,quarantine)
    plan['mode']='STAGED_COLD_RESET'
    plan['oldDataPurged']=False
    print(json.dumps(plan,indent=2))
    return 0


if __name__=='__main__':
    try:
        sys.exit(run())
    except (OSError,ValueError,subprocess.TimeoutExpired,TypeError) as exc:
        print('MAC_SAAS_RESET_DENIED: '+str(exc)[:220],file=sys.stderr)
        sys.exit(2)
