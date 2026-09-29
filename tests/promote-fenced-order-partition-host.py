#!/usr/bin/env python3
"""Promote one fenced disposable-test Order partition using ZK CAS.

The code does not mark local readiness. OrderSvr's normal commit/recovery and
replicated snapshot barriers must prove the new epoch before routing opens.
"""
import argparse
import hashlib
import json
import re
import subprocess

try:
    from tests.md_cluster_transition_host import DockerZk
except ModuleNotFoundError:
    from md_cluster_transition_host import DockerZk


ROOT = '/dc/cluster/ordersvr/partitions'
NODE_CONTAINER = {'OrderSvrA': 'dc-saas-ordersvr', 'OrderSvrB': 'dc-saas-ordersvr-b'}
NODE_DIR = {'OrderSvrA': 'OrderSvrA', 'OrderSvrB': 'OrderSvrB'}


def snapshot(node, partition):
    path = '/srv/dc/data/%s/snapshot/%s/snapshot.json' % (NODE_DIR[node], partition)
    data = subprocess.check_output(['docker', 'exec', NODE_CONTAINER[node], 'cat', path])
    return json.loads(data), hashlib.sha256(data).hexdigest()


def promotion(current, target, partition, expected_epoch):
    if current.get('partitionId') != partition or current.get('state') != 'READY':
        raise ValueError('partition identity/state mismatch')
    if current.get('epoch') != expected_epoch or current.get('primary') == target:
        raise ValueError('partition epoch/primary changed')
    source = current['primary']
    if source not in NODE_CONTAINER or target not in NODE_CONTAINER or current.get('replica') != target:
        raise ValueError('target must be the configured Order A/B replica')
    desired = dict(current)
    desired['epoch'] = expected_epoch + 1
    desired['primary'] = target
    desired['replica'] = source
    if 'assignmentVersion' in desired:
        desired['assignmentVersion'] = int(desired['assignmentVersion']) + 1
    return desired


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--partition', required=True)
    ap.add_argument('--to-node', required=True, choices=sorted(NODE_CONTAINER))
    ap.add_argument('--expected-epoch', type=int, required=True)
    ap.add_argument('--zk-port', type=int, default=32181)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--confirm-partition')
    args = ap.parse_args()
    if not re.fullmatch(r'P[0-9]{3}', args.partition) or args.expected_epoch <= 0:
        ap.error('invalid partition or epoch')
    if args.apply and args.confirm_partition != args.partition:
        ap.error('--apply requires exact --confirm-partition')

    zk = DockerZk('dc-saas-zookeeper', '127.0.0.1:%s' % args.zk_port, ROOT,
                  client_jvmflags='-Djava.security.auth.login.config=/conf/jaas.ini')
    current = zk.read(args.partition)
    desired = promotion(current['value'], args.to_node, args.partition, args.expected_epoch)
    before, before_hash = snapshot(current['value']['primary'], args.partition)
    replica, replica_hash = snapshot(args.to_node, args.partition)
    if before_hash != replica_hash or before.get('partitionId') != args.partition \
            or before.get('epoch') != args.expected_epoch or replica.get('epoch') != args.expected_epoch:
        raise ValueError('matching same-epoch snapshots on both nodes required')
    print('ORDER_PARTITION_PROMOTION_PLAN partition=%s zkVersion=%s source=%s target=%s '
          'epoch=%s->%s snapshotSeq=%s snapshotSha256=%s' % (
              args.partition, current['version'], current['value']['primary'], args.to_node,
              args.expected_epoch, desired['epoch'], before.get('snapshotSeq'), before_hash))
    if args.apply:
        written = zk.cas(current, desired)
        print('ORDER_PARTITION_PROMOTION_CAS_PASS partition=%s zkVersion=%s epoch=%s '
              'localReadiness=UNVERIFIED' % (args.partition, written['version'], desired['epoch']))


if __name__ == '__main__':
    main()
