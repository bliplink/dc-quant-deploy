#!/usr/bin/env python3
"""T87 candidate release gate. 0=one Common engine only; 2=NO-GO.

Read-only: never mutates Demo, Docker, MySQL, or test/HA evidence volumes.
"""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
for name in ('common', 'demo', 'order', 'trade', 'dc'):
    parser.add_argument('--' + name, required=True, type=Path)
parser.add_argument('--demo-common-jar', required=True, type=Path)
args = parser.parse_args()
roots = {name: getattr(args, name) for name in ('common', 'demo', 'order', 'trade', 'dc')}
fail = []
passed = []


def check(label, condition):
    (passed if condition else fail).append(label)


shared = roots['common'] / 'src/main/java/com/app/common'
for item in (
    'partition/PartitionFailoverController.java',
    'partition/ZkPartitionFailoverRuntime.java',
    'replication/ReplicatedStateMachine.java',
    'replication/NodeClusterControlManager.java',
    'replication/CertifiedNodeRecoveryGate.java',
    'replication/DurableWalGroupCommit.java',
    'replication/VerifiedRecoveryStagingClient.java',
    'replication/DurableWalCustodyReceiptLedger.java',
):
    check('Common owns ' + item, (shared / item).is_file())
for name, relative in (
    ('demo', 'com/opentradingcore/demo/DemoStateMachine.java'),
    ('order', 'com/app/dc/service/cluster/OrderRecoveryStateMachine.java'),
    ('trade', 'com/app/dc/service/cluster/TradeRecoveryStateMachine.java'),
):
    file = roots[name] / ('src/main/java/' + relative)
    check(name + ' implements Common ReplicatedStateMachine',
          file.is_file() and 'implements ReplicatedStateMachine' in file.read_text())

# All these are still service-/Demo-owned cluster authority, not business state.
# Do not suppress this release gate by renaming; remove the reachable logic.
legacy = {
    'demo': (
        'DemoV19SafeTakeover.java',
        'DemoV19Rf2StrictAckRuntime.java',
        'DemoV19DurableRuntime.java',
        'DemoV19NodeGrantBridge.java',
    ),
    'order': (
        'OrderReplicationManager.java',
        'OrderReplicaRepairCoordinator.java',
        'OrderPartitionRecoveryManager.java',
        'OrderSnapshotReplicationManager.java',
        'OrderFailoverProofControlHandler.java',
    ),
    'trade': (
        'TradeFailoverController.java',
        'TradeFailoverAssignmentTransition.java',
        'TradeFailoverControlPlaneClient.java',
        'TradeReplicationManager.java',
        'TradeCertifiedRecoveryReceiver.java',
    ),
}
for name, classes in legacy.items():
    root = roots[name] / 'src/main/java'
    for cls in classes:
        check(f'No {name} duplicate cluster owner {cls}', not any(root.rglob(cls)))
for name, relative, pattern in (
    ('trade', 'com/app/dc/service/cluster/TradeCertifiedGenesisReplicaObserver.java', '.casAssignment('),
    ('order', 'com/app/dc/service/cluster/OrderReplicaRepairCoordinator.java', 'store.compareAndSet('),
    ('trade', 'com/app/dc/service/cluster/TradePartitionLifecycleManager.java', 'PartitionReadinessGuard.markReady('),
    ('order', 'com/app/dc/service/cluster/OrderPartitionLifecycleManager.java', 'PartitionReadinessGuard.markReady('),
):
    source = roots[name] / 'src/main/java' / relative
    check(f'No {name} direct cluster transition {relative}: {pattern}',
          not source.is_file() or pattern not in source.read_text())

# Ensure clean image dependency directories contain exactly ONE identical Common.
deps = {
    'demo': roots['demo'] / 'pom.xml',
    'order': roots['order'] / 'target/dependency',
    'trade': roots['trade'] / 'target/javalib',
}
sha = {}
for name in ('order', 'trade'):
    matches = sorted(deps[name].glob('com.app.common-*.jar'))
    check(f'{name} image has exactly one Common JAR', len(matches) == 1)
    if len(matches) == 1:
        sha[name] = hashlib.sha256(matches[0].read_bytes()).hexdigest()
if args.demo_common_jar.is_file():
    sha['demo'] = hashlib.sha256(args.demo_common_jar.read_bytes()).hexdigest()
check('Demo Order Trade Common JAR SHA256 exactly identical',
      all(x in sha for x in ('demo','order','trade'))
      and len(set(sha.values())) == 1)
check('Demo POM declares T87 singlecore',
      deps['demo'].is_file() and '3.0.22-t87-singlecore-20261024-SNAPSHOT' in deps['demo'].read_text())
check('dc POM pins same T87 singlecore',
      (roots['dc'] / 'pom.xml').is_file() and
      '3.0.22-t87-singlecore-20261024-SNAPSHOT' in (roots['dc'] / 'pom.xml').read_text())

print(json.dumps({'decision': 'GO' if not fail else 'NO-GO',
                  'passed': passed, 'blocking': fail, 'sha256': sha},
                 ensure_ascii=False, indent=2))
raise SystemExit(0 if not fail else 2)
