#!/usr/bin/env python3
"""Check Common owns HA; this is a source boundary check, NOT a HA PASS."""
import argparse
import pathlib
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--common', type=pathlib.Path, required=True)
ap.add_argument('--order', type=pathlib.Path, required=True)
ap.add_argument('--trade', type=pathlib.Path, required=True)
ap.add_argument('--mode', choices=('business','production'), default='business')
a = ap.parse_args()
failures = []

def read(root, name):
    found = list(root.glob('src/main/java/**/'+name))
    if len(found) != 1:
        failures.append('missing or duplicate '+name+' in '+str(root))
        return ''
    return found[0].read_text(encoding='utf-8')

common_interface = read(a.common, 'ReplicatedStateMachine.java')
fence = read(a.common, 'CommonCertifiedRecoveringBusinessFence.java')
order_machine = read(a.order, 'OrderRecoveryStateMachine.java')
trade_machine = read(a.trade, 'TradeRecoveryStateMachine.java')
trade_applier = read(a.trade, 'TradeRecoveryApplier.java')
trade_binding = read(a.trade, 'TradeCommonRecoveryBinding.java')
for method in ('void apply(byte[] command)', 'void snapshot(ChunkSink sink)', 'void restore(ChunkSource source)'):
    if method not in common_interface:
        failures.append('Common business API missing '+method)
for service, source in (('Order', order_machine), ('Trade', trade_machine)):
    if 'implements ReplicatedStateMachine' not in source:
        failures.append(service+' must implement existing Common state machine')
    for forbidden in ('CommonCertifiedFailoverCoordinator', 'ZookeeperClient', 'ZkNodeScopedControlPlane',
                      'CommonCertifiedFailoverWatch', '.stageRecovering(', '.publishCertifiedReady('):
        if forbidden in source:
            failures.append(service+' domain machine contains physical HA: '+forbidden)
for forbidden in ('CommonCertifiedFailoverCoordinator', '.requireCurrentRecoveringStage(',
                  '.stageRecovering(', '.publishCertifiedReady('):
    if forbidden in trade_applier:
        failures.append('Trade business mutation layer contains HA: '+forbidden)
if 'requireCurrentRecoveringStage(stage)' not in fence:
    failures.append('Common recovering gate not authenticating current Stage')
if 'private CommonCertifiedRecoveringBusinessFence(' not in fence or 'public void requireCurrent()' not in fence:
    failures.append('Common recovering gate must be an unforgeable private-constructor capability')
if 'CommonCertifiedRecoveringBusinessFence independentlyCertifiedCommonFence' not in trade_applier:
    failures.append('Trade funds recovery must require Common capability, not a no-op Runnable')
if 'CommonCertifiedRecoveringBusinessFence' not in trade_binding:
    failures.append('Trade binding not using Common signed recovering gate')

if a.mode == 'production':
    # Target state, NOT a workaround that makes current NO-GO disappear.
    for service, root in (('Order',a.order),('Trade',a.trade)):
        for file in root.glob('src/main/java/**/*.java'):
            code=file.read_text(encoding='utf-8')
            if re.search(r'@Qualifier\s*\(\s*"(?:order|trade)CommonCertifiedPhysicalRecovery"\s*\)', code):
                failures.append(service+' still injects service-specific physical recovery: '+str(file))
    actual=list(a.common.glob('src/main/java/**/CommonCertifiedProductionPhysicalRecovery.java'))
    if len(actual) != 1:
        failures.append('Common complete production physical recovery executor NOT implemented')

if failures:
    for problem in failures:
        print('FAIL: '+problem)
    sys.exit(1)
print('PASS: Common-only HA '+a.mode+' source boundary (not live HA acceptance)')
