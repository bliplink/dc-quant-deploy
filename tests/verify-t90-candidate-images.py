#!/usr/bin/env python3
"""Read-only real Docker-image Common/Order/Trade T90 pre-release gate.

No container startup, Docker network, volume mutation, image modification or
credential handling. A staged candidate may pass its binary parity checks,
while the formal release verdict MUST remain NO-GO for private cluster logic.
"""
import argparse
import json
import subprocess
import sys

EXPECTED_COMMON = 'cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3'
SERVICES = {
    'order': {
        'directory': 'OrderSvr',
        'expected_deleted': ['OrderReplicaRepairCoordinator'],
        'not_yet_migrated': [
            'OrderReplicationManager', 'OrderPartitionRecoveryManager',
            'OrderSnapshotReplicationManager', 'OrderFailoverProofControlHandler'],
    },
    'trade': {
        'directory': 'TradeSvr',
        'expected_deleted': ['TradeCertifiedGenesisReplicaObserver'],
        'not_yet_migrated': [
            'TradeFailoverControlPlaneClient', 'TradeReplicationManager',
            'TradeCertifiedRecoveryReceiver'],
    },
}


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=40)


def audit_image(service, image):
    root = '/srv/dc/dc/' + SERVICES[service]['directory']
    info = json.loads(run(['docker', 'image', 'inspect', image]))[0]
    labels = info['Config'].get('Labels') or {}
    if info.get('Architecture') != 'arm64' or info.get('Os') != 'linux':
        raise RuntimeError('unexpected architecture')
    if labels.get('dc.common.jar.sha256') != EXPECTED_COMMON:
        raise RuntimeError('image label Common SHA mismatched')
    if labels.get('dc.release.authorized') != 'false':
        raise RuntimeError('candidate must be labeled as NOT authorized for live release')
    names = SERVICES[service]
    forbidden = names['expected_deleted'] + names['not_yet_migrated']
    fragment = '\n'.join([
        'set -e',
        'lib=' + root + '/lib',
        'test "$(find "$lib" -maxdepth 1 -name "com.app.common*.jar" | wc -l)" -eq 1',
        'test "$(find "$lib" -maxdepth 1 -name "com.app.dc-*.jar" | wc -l)" -eq 1',
        'sha256sum "$lib"/com.app.common-*.jar | cut -d " " -f1',
    ] + ['test -f ' + root + '/classes/com/app/dc/service/cluster/' + cls + '.class && echo PRESENT:' + cls + ' || echo ABSENT:' + cls for cls in forbidden])
    proof = run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                 '--entrypoint', '/bin/sh', image, '-c', fragment])
    lines = proof.strip().splitlines()
    if not lines or lines[0] != EXPECTED_COMMON:
        raise RuntimeError('image contains unexpected Common bytes')
    for cls in names['expected_deleted']:
        if 'PRESENT:' + cls in lines:
            raise RuntimeError('previously removed service cluster class is packaged: ' + cls)
    present = [cls for cls in names['not_yet_migrated'] if 'PRESENT:' + cls in lines]
    return {'service': service, 'image': image, 'image_id': info['Id'],
            'shared_common_sha256': EXPECTED_COMMON,
            'removed_private_cluster_classes_absent': True,
            'remaining_private_cluster_classes': present,
            'network_used': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order-image', default='local/otc-t90-ordersvr:common-t87-7dcccf6')
    parser.add_argument('--trade-image', default='local/otc-t90-tradesvr:common-t87-47644f4')
    parser.add_argument('--strict-release', action='store_true', help='Fail closed until all private owners are gone')
    args = parser.parse_args()
    reports = [audit_image('order', args.order_image), audit_image('trade', args.trade_image)]
    blockers = [cls for report in reports for cls in report['remaining_private_cluster_classes']]
    result = {'artifact_preflight': 'PASS', 'release_decision': 'NO-GO' if blockers else 'SOURCE_GATE_REQUIRED',
              'blocking_private_classes': blockers, 'images': reports}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if args.strict_release and blockers else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as error:
        print('CANDIDATE_IMAGE_PREFLIGHT_FAILED:', str(error), file=sys.stderr)
        sys.exit(3)
