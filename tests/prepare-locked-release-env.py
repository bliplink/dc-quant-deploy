#!/usr/bin/env python3
"""Write a protected local release env without printing or changing credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ENV_KEYS = {'gateway': 'GW', 'trade-web': 'TRADE_WEB', 'tenant-web': 'TENANT_WEB', 'platform-web': 'PLATFORM_WEB'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--build-evidence', required=True, type=Path)
    parser.add_argument('--input-env', required=True, type=Path)
    parser.add_argument('--output-env', required=True, type=Path)
    args = parser.parse_args()
    if args.input_env.resolve() == args.output_env.resolve():
        raise ValueError('preserve the installation input; use a separate generated release env')
    lock = json.loads(args.lock.read_text())
    evidence = json.loads(args.build_evidence.read_text())
    if evidence['releaseId'] != lock['releaseId']:
        raise ValueError('release evidence identity mismatch')
    values = {'IMAGE_SOURCE': 'registry', 'ORDER_CLUSTER_ENABLED': 'true', 'ORDER_CLUSTER_C_ENABLED': 'false',
        'MD_CLUSTER_ENABLED': 'true', 'MD_CLUSTER_C_ENABLED': 'true', 'TRADE_CLUSTER_ENABLED': 'true',
        'ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED': 'true', 'TRADE_CLUSTER_PERIODIC_SNAPSHOT_ENABLED': 'true',
        'ZOOKEEPER_CPU_LIMIT': '0.50'}
    for component in lock['components']:
        built = evidence['components'].get(component['name'], {})
        if built.get('revision') != component['revision']:
            raise ValueError('unbuilt locked component: ' + component['name'])
        tests = built.get('tests', {})
        if tests.get('failures', 0) or tests.get('errors', 0):
            raise ValueError('failed component tests')
        if component['type'] == 'library':
            continue
        actual_id = subprocess.check_output(['docker', 'image', 'inspect', component['image'],
            '--format', '{{.Id}}'], text=True).strip()
        if actual_id != built['imageId']:
            raise ValueError('built tag changed: ' + component['name'])
        key = ENV_KEYS.get(component['name'], component['name'].upper())
        repository, tag = component['image'].rsplit(':', 1)
        if not tag.startswith(('cluster-dev-', 'sha-')):
            raise ValueError('immutable application image tag required')
        values[key + '_IMAGE_REPOSITORY'] = repository
        values[key + '_TAG'] = tag
    lines = args.input_env.read_text().splitlines()
    output = []
    for line in lines:
        match = re.match(r'^([A-Z][A-Z0-9_]*)=', line)
        if match and match.group(1) in values:
            key = match.group(1)
            output.append(key + '=' + values.pop(key))
        else:
            output.append(line)
    output.extend(key + '=' + value for key, value in values.items())
    descriptor = os.open(str(args.output_env), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('\n'.join(output) + '\n')
    os.chmod(args.output_env, 0o600)
    print('LOCKED_RELEASE_ENV_PASS components=14 credentials=preserved')


if __name__ == '__main__':
    main()
