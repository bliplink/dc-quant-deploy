#!/usr/bin/env python3
"""Inspect a running Mac Demo voter's cached recovery reason and control-plane census."""
import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import tempfile

HERE = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(HERE / 'verify-mac-demo-runtime.py'))
run, inspect, identity = (RUNTIME[k] for k in ('run', 'inspect', 'process_identity'))
manifest = runpy.run_path(str(HERE / 'verify-mac-demo-async-rpo.py'))['manifest']


def census(rows):
    counts = collections.Counter((r['primary'], r['epoch'], r['state'], r['policy']) for r in rows.values())
    return [dict(primary=k[0], epoch=k[1], state=k[2], policy=k[3], count=v)
            for k, v in sorted(counts.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    parser.add_argument('service', choices=['order', 'trade'])
    parser.add_argument('slot', choices=['A', 'B'], help='Running voter to inspect')
    parser.add_argument('partition', help='Partition whose cached watch should be inspected')
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    if (root.parent != (Path.home()/'.opentradingcore').resolve()
            or not re.fullmatch(r'mac-demo-\d{8}-\d{6}', root.name)
            or not re.fullmatch(r'P\d{3}', args.partition) or int(args.partition[1:]) >= 256):
        parser.error('Expected an original Mac Demo directory and P000 through P255')
    os.umask(0o077)
    service = {'order': 'OrderSvr', 'trade': 'TradeSvr'}[args.service]
    name = f'{root.name}-{args.service}-{args.slot.lower()}-hostready'
    node = inspect(name)
    gateway = inspect('dc-saas-gateway')
    if (gateway['Config']['Labels'].get('com.docker.compose.project') != root.name
            or node['Config']['Labels'].get('otc.mac.demo.generation') != root.name
            or not node['State']['Running'] or not gateway['State']['Running']):
        parser.error('The selected generation must be active and the specified voter running')
    before = manifest(root, args.service)
    if len(before) != 256 or args.partition not in before:
        raise RuntimeError('Incomplete control-plane census')
    work = Path(tempfile.mkdtemp(prefix='recovery-observation-', dir=root))
    observer = 'T554CommonRecoveryProgressReadAgent'
    source = HERE.parent / 'tests/fixtures/async-rpo'
    java = Path(run('/usr/libexec/java_home', '-v', '1.8').strip())
    run(java/'bin/javac', '-cp', java/'lib/tools.jar', '-d', work,
        source/(observer+'.java'), source/'T554RpoAttach.java')
    mf = work/'MANIFEST.MF'
    mf.write_text('Manifest-Version: 1.0\nAgent-Class: '+observer+'\n\n')
    run(java/'bin/jar', 'cfm', work/'observer.jar', mf, '-C', work, observer+'.class')
    remote = '/tmp/'+work.name
    node_id = node['Id']
    run('docker', 'cp', work, node_id+':'+remote)
    run('docker', 'exec', node_id, 'java', '-cp', '/opt/java/openjdk/lib/tools.jar:'+remote,
        'T554RpoAttach', '1', remote+'/observer.jar', remote+'/cached.txt,'+args.partition)
    cached = run('docker', 'exec', node_id, 'cat', remote+'/cached.txt')
    if not cached.startswith('scope=CACHED_RECOVERY_DIAGNOSTIC_NOT_AUTHORITY\npartition='+args.partition+'\n'):
        raise RuntimeError('Cached observer returned an unexpected partition or scope')
    common = run('docker', 'exec', node_id, 'sha256sum', '/srv/dc/dc/'+service+'/lib/com.app.common-mac-demo.jar').split()[0]
    after = manifest(root, args.service)
    if identity(inspect(name)) != identity(node) or identity(inspect('dc-saas-gateway')) != identity(gateway):
        raise RuntimeError('The selected process or active generation changed during observation')
    data = {'scope': 'Read-only observation; no writer, recovery or READY authority',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'container': name, 'container_id': node_id,
            'started_at': node['State']['StartedAt'], 'restarts': node['RestartCount'], 'common_sha256': common,
            'partition': args.partition, 'route_before': before[args.partition], 'route_after': after[args.partition],
            'census_before': census(before), 'census_after': census(after), 'census_unchanged': before == after,
            'observer_source_sha256': hashlib.sha256((source/(observer+'.java')).read_bytes()).hexdigest(),
            'cached': cached.splitlines()[2:]}
    output = work/'observation.json'
    output.write_text(json.dumps(data, indent=2)+'\n')
    print(cached.strip())
    print(output)


if __name__ == '__main__':
    main()
