#!/usr/bin/env python3
"""Explicit disposable-test reset. Never deletes code, config, or Maven cache."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import time

ROOTS = {'/data/dc-saas-runtime', '/opt/dc-saas-runtime'}
COMPONENTS = ('APSSvr', 'OrderSvr', 'OrderSvrA', 'OrderSvrB', 'OrderSvrC',
              'TradeSvr', 'TradeSvrA', 'TradeSvrB', 'MDSvr', 'MDSvrA', 'MDSvrB', 'MDSvrC',
              'ProjectionSvr', 'RobotSvr', 'mysql', 'clickhouse', 'zookeeper')


def exact_targets(root):
    root = Path(root)
    if str(root) not in ROOTS or root.resolve() != root:
        raise ValueError('unsupported/canonical test runtime root')
    for ancestor in (root, *root.parents, root / 'data', root / 'log', root / 'evidence'):
        if ancestor.is_symlink():
            raise ValueError(f'symbolic-link ancestor refused: {ancestor}')
    data = root / 'data'
    if not data.is_dir():
        raise ValueError('test data directory must already exist')
    unknown = {path.name for path in data.iterdir()} - set(COMPONENTS)
    if unknown:
        raise ValueError(f'unrecognized data components; inspect before reset: {sorted(unknown)}')
    if any(path.is_symlink() for path in data.iterdir()):
        raise ValueError('symbolic-link component refused (including dangling links)')
    targets = [data / name for name in COMPONENTS if (data / name).exists()]
    # ZooKeeper's /datalog is a second authoritative volume, NOT an application
    # text log. Removing /data alone leaves orphan transactions and prevents a
    # fresh startup ("No snapshot found, but there are log entries").
    for name in ('zookeeper', 'clickhouse'):
        target = root / 'log' / name
        if target.is_symlink():
            raise ValueError('linked infrastructure log volume refused')
        if target.exists():
            targets.append(target)
    device = data.stat().st_dev
    mounts = [Path(line.split()[4].replace('\\040', ' ')) for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    for target in targets:
        if target.is_symlink() or target.resolve() != target or not target.is_dir() or target.stat().st_dev != device:
            raise ValueError(f'unsafe component target: {target}')
        if any(mount == target or target in mount.parents for mount in mounts):
            raise ValueError(f'nested mount refused: {target}')
    return targets


def require_uninstalled(root):
    ids = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
    if not ids:
        return
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True))
    for container in containers:
        name = container['Name'].lstrip('/')
        if name.startswith('dc-saas-'):
            raise ValueError(f'run normal uninstall first; container still exists: {name}')
        for mount in container.get('Mounts', []):
            source = Path(mount['Source'])
            if source == root or root in source.parents:
                raise ValueError(f'other container uses test runtime: {name}')


def require_closed(targets):
    # Scan open descriptors across host and container PIDs after uninstall.
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            descriptors = list((process / 'fd').iterdir())
        except FileNotFoundError:
            continue
        except PermissionError as error:
            raise ValueError(f'cannot inspect PID {process.name}') from error
        for descriptor in descriptors:
            try:
                destination = Path(descriptor.readlink().as_posix().removesuffix(' (deleted)'))
            except FileNotFoundError:
                continue
            except PermissionError as error:
                raise ValueError(f'cannot inspect descriptor {descriptor}') from error
            if any(destination == target or target in destination.parents for target in targets):
                raise ValueError(f'open data descriptor refused: PID={process.name} target={destination}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--reset-id', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-root')
    args = parser.parse_args()
    if not re.fullmatch(r'reset-[a-zA-Z0-9-]{8,80}', args.reset_id):
        raise ValueError('invalid unique reset ID')
    root = args.runtime_root
    targets = exact_targets(root)
    print(json.dumps(dict(dryRun=not args.apply, runtimeRoot=str(root), targets=list(map(str, targets)),
                         backup=False, retained=['code', 'installation env', 'control', 'evidence', 'build cache'])))
    if not args.apply:
        return
    if args.confirm_root != str(root):
        raise ValueError('apply requires exact --confirm-root')
    import os
    if os.geteuid() != 0:
        raise ValueError('apply requires root')
    import fcntl
    with open('/tmp/dc-saas-auto-update.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_uninstalled(root)
        require_closed(targets)
        # Re-resolve all targets immediately before the exact, one-filesystem removal.
        if targets != exact_targets(root):
            raise ValueError('data inventory changed during preflight')
        evidence = root / 'evidence'
        evidence.mkdir(exist_ok=True)
        proof = evidence / (args.reset_id + '.json')
        with proof.open('x') as output:
            output.write(json.dumps(dict(resetId=args.reset_id, runtimeRoot=str(root),
                dataResetCompleted=False, startedAtMillis=int(time.time() * 1000), backup=False)) + '\n')
        subprocess.run(['rm', '-rf', '--one-file-system', '--', *map(str, targets)], check=True)
        if any(target.exists() for target in targets):
            raise ValueError('reset did not remove every target; no completed proof emitted')
        result = dict(resetId=args.reset_id, runtimeRoot=str(root), dataResetCompleted=True,
            completedAtMillis=int(time.time() * 1000), backup=False,
            deletedComponents=[path.name for path in targets if path.parent == root / 'data'],
            deletedInfrastructureLogDirs=[str(path) for path in targets if path.parent == root / 'log'],
            retained=['control', 'evidence', 'build cache'])
        proof.write_text(json.dumps(result, indent=2) + '\n')
        print(f'RESET_PASS components={len(targets)} proof={proof} recoverable=false')


if __name__ == '__main__':
    main()
