#!/usr/bin/env python3
"""Read-only fail-closed preflight for Common-only physical automatic HA.

Order/Trade must inject one Common post-open factory, not their own physical
producer. Still NO-GO until Common's REAL service-neutral physical executor
exists, and even then a source scan cannot replace actual Docker E2E.
"""
import argparse
import hashlib
from pathlib import Path
import re
import sys

SERVICE_NODE_WIRING = {
    'OrderSvr': ('order', 'OrderCommonNodeRuntimeWiring.java'),
    'TradeSvr': ('trade', 'TradeCommonNodeRuntimeWiring.java'),
}


def without_comments(source):
    # Keep the @Bean signature parse robust against commented-out examples.
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return re.sub(r'(?m)//[^\n]*', '', source)


def check_service(name, root, wiring_file):
    folder = root / 'src/main/java/com/app/dc/service/state'
    main = folder / wiring_file
    if not main.is_file():
        return False, f'{name}:COMMON_NODE_BOOTSTRAP_SOURCE_MISSING:{main}'
    source = without_comments(main.read_text(encoding='utf-8'))
    bad = []
    for file in sorted(folder.rglob('*.java')):
        content = without_comments(file.read_text(encoding='utf-8'))
        if re.search(r'@Qualifier\s*\(\s*"(?:order|trade)CommonCertifiedPhysicalRecovery"\s*\)', content):
            bad.append(file.name + ':service-owned physical recovery qualifier')
        if 'CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery' in content:
            bad.append(file.name + ':service-created physical recovery')
        if re.search(r'@Bean\s*\(\s*name\s*=\s*"(?:order|trade)CommonAutomaticReplicaPlans"', content):
            bad.append(file.name + ':service-owned automatic plan producer')
    if bad:
        return False, f'{name}:SERVICE_PHYSICAL_CLUSTER_IMPLEMENTATION_NOT_ALLOWED:{bad}'
    binding = folder / (name[:-3] + 'CommonFirstReadyE2Wiring.java')
    if binding.is_file():
        first_ready = without_comments(binding.read_text(encoding='utf-8'))
        required = ('CommonCertifiedFirstReadyE2NodeBinding.forDedicatedVoterProcess()',
                    'binding.useReadOnlyReturningPeerVolume(', 'return binding.open(',
                    'CommonCertifiedPartitionAssignments.all(manager)',
                    '.common.nodeRuntime.automaticRecovery', 'havingValue="true"',
                    '.common.nodeRuntime.witnessRoot:')
        if not all(token in first_ready for token in required):
            return False, f'{name}:COMMON_FIRST_READY_BINDING_OR_PROCESS_LIFECYCLE_MISSING'
        return True, f'{name}:COMMON_FIRST_READY_BINDING_SOURCE_ONLY'
    requirements = (
        'CommonCertifiedNodeBootstrap.CertifiedPhysicalRecoveryPlanFactory',
        'openAndStartWithCertifiedAutomaticRecoveryFromOpenedPhysical(',
        'CommonCertifiedNodeBootstrap',
    )
    if not all(token in source for token in requirements):
        return False, f'{name}:COMMON_POSTOPEN_FACTORY_NOT_WIRED'
    if 'openAndStartWithCertifiedAutomaticRecoveryFromPhysicalSources(' in source:
        return False, f'{name}:OLD_PREOPEN_PHYSICAL_PLAN_ENTRY_FORBIDDEN'
    return True, f'{name}:COMMON_POSTOPEN_FACTORY_BUSINESS_WIRING_ONLY'


def check_common_executor(root, first_ready_binding=False):
    file = root / ('src/main/java/com/app/common/replication/'
                   'CommonCertifiedProductionPhysicalRecovery.java')
    if not file.is_file():
        return False, 'COMMON_PRODUCTION_AUTO_PHYSICAL_RECOVERY_EXECUTOR_MISSING'
    content = without_comments(file.read_text(encoding='utf-8'))
    if not re.search(r'implements\s+CommonCertifiedAutomaticReplicaPlanWiring\.DurablePhysicalRecovery\b', content):
        return False, 'COMMON_PRODUCTION_EXECUTOR_DOES_NOT_IMPLEMENT_REAL_PHYSICAL_CONTRACT'
    # Structure is necessary, NOT sufficient. A class name, empty callbacks,
    # or a fake Bean must never be misrepresented as successful runtime HA.
    cross_epoch = ('CommonCertifiedStrictCrossEpochSurvivorInstall' if first_ready_binding
                   else 'CommonCertifiedCrossEpochSurvivorInstall')
    required = ('signedCoordinator(', 'independentFsyncedReplica(',
                'bothSignedPhysicalReady(', 'recoveredBusinessWalAndSnapshot(',
                'CommonCertifiedPhysicalEvidenceRegistry',
                'CommonDurableFailoverStageLedger',
                'CommonCertifiedGenesisSurvivorInstall',
                cross_epoch)
    # T547: the existing executor has all the right class names but still
    # hard-rejects E2+ at its real physical factory. This previously reported
    # a misleading source-only PASS while Order/Trade ran E2 STRICT. Do not
    # infer recoverability from callbacks when current-Epoch proof is absent.
    original_e1_only = (
        r'\bprior\s*\.\s*epoch\s*!=\s*1\b',
        r'\ba\s*\.\s*getEpoch\s*\(\s*\)\s*!=\s*1\b',
    )
    if not first_ready_binding and any(re.search(rule, content) for rule in original_e1_only):
        return False, 'COMMON_PRODUCTION_E1_ONLY_E2_STRICT_ROLLING_NOT_SUPPORTED'
    # T554: an executor that removes the top-level E1 check can still
    # hard-reject current-Epoch rolling recovery inside later callbacks.
    # Keep this source-only guard fail-closed until independently verified
    # E(n)->E(n+1) physical custody/commit-index is actually wired.
    stage_e1_only = (
        r'\bstage\s*\.\s*previousEpoch\s*!=\s*1\b',
        r'\bstage\s*\.\s*nextEpoch\s*!=\s*2\b',
    )
    if any(re.search(rule, content) for rule in stage_e1_only):
        return False, 'COMMON_PRODUCTION_STAGE_E1_TO_E2_ONLY_ROLLING_NOT_SUPPORTED'
    if not all(token in content for token in required):
        return False, 'COMMON_PRODUCTION_EXECUTOR_MISSING_ACTUAL_WAL_RSA_RECOVERY_STEPS'
    if first_ready_binding:
        binding = file.with_name('CommonCertifiedFirstReadyE2NodeBinding.java')
        if not binding.is_file():
            return False, 'COMMON_FIRST_READY_BINDING_SOURCE_MISSING'
        source = without_comments(binding.read_text(encoding='utf-8'))
        required = ('CommonCertifiedProductionPhysicalRecovery.forFirstReadyE2(',
                    'CommonCertifiedWitnessedReturnCensus.verify(',
                    'CommonCertifiedStrictHomeHistory.verify(',
                    'new CommonCertifiedWitnessedReturnRunner(',
                    'manager.onIrrecoverableNodeFence(', 'manager.enableSignedPoisonNotice(',
                    'forDedicatedVoterProcess()', 'System.exit(78)')
        if 'forFirstReadyE2(' not in content or not all(token in source for token in required):
            return False, 'COMMON_FIRST_READY_CURRENT_EPOCH_OR_PROCESS_LIFECYCLE_MISSING'
        return True, 'COMMON_FIRST_READY_SOURCE_ONLY_REAL_PHYSICAL_HA_STILL_REQUIRED'
    return True, 'COMMON_EXECUTOR_SOURCE_ONLY_CURRENT_EPOCH_MUST_STILL_PASS_REAL_HA'


def digest(file):
    h = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--order-root', type=Path, default=Path('.work/t444-order-stream'))
    p.add_argument('--trade-root', type=Path, default=Path('.work/t452-trade-windowed-e2'))
    p.add_argument('--common-root', type=Path, default=Path('.work/t472-common-publish-20261104'))
    p.add_argument('--order-common-jar', type=Path)
    p.add_argument('--trade-common-jar', type=Path)
    args = p.parse_args()
    checked = []
    for service, (arg, wiring) in SERVICE_NODE_WIRING.items():
        result = check_service(service, getattr(args, arg + '_root'), wiring)
        checked.append(result)
        print(('PASS' if result[0] else 'NO-GO') + ':T507_' + result[1])
    first_ready = all((root / 'src/main/java/com/app/dc/service/state' /
                       (service[:-3] + 'CommonFirstReadyE2Wiring.java')).is_file()
                      for service, root in (('OrderSvr', args.order_root), ('TradeSvr', args.trade_root)))
    common_result = check_common_executor(args.common_root, first_ready_binding=first_ready)
    checked.append(common_result)
    print(('PASS' if common_result[0] else 'NO-GO') + ':T507_' + common_result[1])
    if bool(args.order_common_jar) != bool(args.trade_common_jar):
        checked.append((False, 'both exact Common JAR paths required'))
        print('NO-GO:T489_BOTH_SERVICE_COMMON_JARS_REQUIRED')
    elif args.order_common_jar:
        if not args.order_common_jar.is_file() or not args.trade_common_jar.is_file():
            checked.append((False, 'missing jar'))
            print('NO-GO:T489_MISSING_COMMON_JAR')
        else:
            a, b = digest(args.order_common_jar), digest(args.trade_common_jar)
            print(('PASS' if a == b else 'NO-GO') + ':T489_ORDER_TRADE_COMMON_JAR_SHA256:' + a + ':' + b)
            checked.append((a == b, 'same Common JAR'))
    if not all(success for success, _ in checked):
        print('NO-GO:T489_PRODUCTION_AUTOMATIC_HA_NOT_AUTHORIZED')
        return 2
    print('PASS:T507_SOURCE_ONLY_REAL_DEMO_ORDER_TRADE_HA_AND_RUNTIME_PROOF_STILL_REQUIRED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
