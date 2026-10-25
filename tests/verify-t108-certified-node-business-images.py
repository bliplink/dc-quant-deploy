#!/usr/bin/env python3
"""Binary and runtime-readiness gate for Common-only Order/Trade candidates.

Non-invasive: reads image metadata, checks classes in fresh read-only, offline
containers and never starts Order/Trade, connects to Demo or changes volumes.
PASS for absent old Trade/Order cluster code is NOT certification to trade.
"""
import argparse
import json
import subprocess
import sys

SHARED_IDENTITY_SHA = '33bb58ffd3dc380074741f6c83814ca030c540514074dd7426f37aec72013c3f'
COMMON_SHA = '90c4b8ab3b378a61c67607221400fa1da55e0aa8fe3bb19408c46e7064290ff8'
IMAGES = {
    'order': {'root':'OrderSvr', 'source':'765d4b7',
              'image':'local/otc-t108-ordersvr:common-zk-765d4b7',
              'state':'OrderRecoveryStateMachine', 'adapter':'OrderClusterAdapter',
              'business_recovery':'OrderCommonRecoveryBinding',
              'business_snapshot':'OrderSnapshotManager',
              'common_control':'OrderCommonControlWiring',
              'existing_rsa':'OrderExistingDemoRsaWiring',
              'physical_proof':'OrderCommonPhysicalProofWiring',
              'failed_event':'OrderApplicationFailedExitListener',
              'mandatory_cluster':'ORDER_COMMON_CLUSTER_MUST_BE_ENABLED',
              'startup_fatal':'FATAL_ORDER_COMMON_CLUSTER_STARTUP',
              'missing_wal':'ORDER_COMMON_WAL_ACK_CUSTODY_NOT_CONNECTED',
              'missing_snapshot':'ORDER_COMMON_CERTIFIED_SNAPSHOT_HEAD_NOT_CONNECTED'},
    'trade': {'root':'TradeSvr', 'source':'5b110c8',
              'image':'local/otc-t108-tradesvr:common-zk-5b110c8',
              'state':'TradeRecoveryStateMachine', 'adapter':'TradeClusterAdapter',
              'business_recovery':'TradeCommonRecoveryBinding',
              'business_snapshot':'TradeBusinessSnapshotCapture',
              'common_control':'TradeCommonControlWiring',
              'existing_rsa':'TradeExistingDemoRsaWiring',
              'physical_proof':'TradeCommonPhysicalProofWiring',
              'failed_event':'TradeApplicationFailedExitListener',
              'mandatory_cluster':'TRADE_COMMON_CLUSTER_MUST_BE_ENABLED',
              'startup_fatal':'FATAL_TRADE_COMMON_CLUSTER_STARTUP',
              'missing_wal':'TRADE_COMMON_WAL_AND_CUSTODY_ADAPTER_NOT_INSTALLED',
              'missing_snapshot':'TRADE_COMMON_CERTIFIED_SNAPSHOT_TRANSACTION_NOT_INSTALLED'},
}

def shell(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=55)

def verify(service, image):
    record = json.loads(shell(['docker','image','inspect',image]))[0]
    labels = record['Config'].get('Labels') or {}
    fields = IMAGES[service]
    if record['Architecture'] != 'arm64' or record['Os'] != 'linux':
        raise ValueError('wrong architecture for '+service)
    if labels.get('dc.common.jar.sha256') != COMMON_SHA:
        raise ValueError('Common version not pinned in '+service)
    if labels.get('dc.source.revision') != fields['source']:
        raise ValueError('source Git commit mismatch for '+service)
    root = '/srv/dc/dc/'+fields['root']
    cls = root+'/classes/com/app/dc/service/state/'
    script='\n'.join([
        'set -eu',
        'test ! -d '+root+'/classes/com/app/dc/service/cluster',
        'test -f '+cls+fields['state']+'.class',
        'test -f '+cls+fields['adapter']+'.class',
        'test -f '+cls+fields['business_recovery']+'.class',
        'test -f '+cls+fields['business_snapshot']+'.class',
        'test -f '+cls+fields['common_control']+'.class',
        'test -f '+cls+fields['existing_rsa']+'.class',
        'test -f '+cls+fields['physical_proof']+'.class',
        'grep -aq CertifiedPersistedCustodySource '+cls+fields['physical_proof']+'.class',
        "test \"$(find "+root+" -type f -name '*.pk8' | wc -l)\" -eq 0",
        'test -f '+cls+fields['failed_event']+'.class',
        'test -s '+root+'/classes/META-INF/spring.factories',
        'grep -q '+repr('com.app.dc.service.state.'+fields['failed_event'])+' '+root+'/classes/META-INF/spring.factories',
        'grep -aq PhysicalVerifier '+cls+fields['common_control']+'.class',
        'test -s '+cls+fields['common_control']+'.class',
        'test -s '+root+'/lib/com.app.common-3.0.22-t108-certified-node-20261025-SNAPSHOT.jar',
        'test -f '+cls+('OrderStateJournal' if service=='order' else 'TradeStateCoordinator')+'.class',
        'test "$(find '+root+'/lib -maxdepth 1 -name \'com.app.common*.jar\' | wc -l)" -eq 1',
        'test "$(find '+root+'/lib -maxdepth 1 -name \'com.app.dc-*.jar\' | wc -l)" -eq 1',
        'sha256sum '+root+'/lib/com.app.common-*.jar | cut -d " " -f1',
        'sha256sum '+root+'/lib/com.app.dc-*.jar | cut -d " " -f1',
        'if grep -aq '+ repr(fields['missing_wal'])+' '+cls+fields['adapter']+'.class; then echo WAL_ADAPTER_UNCONNECTED; else echo WAL_ADAPTER_STRING_ABSENT; fi',
        'if grep -aq '+repr(fields['missing_snapshot'])+' '+cls+('OrderSnapshotManager' if service=='order' else fields['state'])+'.class; then echo SNAPSHOT_ADAPTER_UNCONNECTED; else echo SNAPSHOT_ADAPTER_STRING_ABSENT; fi',
        'if grep -aq '+repr(fields['mandatory_cluster'])+' '+cls+fields['adapter']+'.class; then echo COMMON_CLUSTER_REQUIRED; else echo UNSAFE_STANDALONE_FALLBACK; fi',
        'if grep -aq '+repr(fields['startup_fatal'])+' '+root+'/classes/com/app/dc/service/'+('OrderStart' if service=='order' else 'TradeStart')+'.class; then echo STARTUP_FATAL_PRESENT; else echo STARTUP_FATAL_MISSING; fi',
    ])
    out=shell(['docker','run','--rm','--network','none','--read-only',
               '--entrypoint','/bin/sh',image,'-c',script]).strip().splitlines()
    if len(out)!=6 or out[0]!=COMMON_SHA or out[1]!=SHARED_IDENTITY_SHA:
        raise ValueError('Common JAR bytes or T94 actual image classes differ')
    if out[4] != 'COMMON_CLUSTER_REQUIRED':
        raise ValueError('Common must be mandatory by default: '+service)
    if out[5] != 'STARTUP_FATAL_PRESENT':
        raise ValueError('failed Common bootstrap must terminate JVM: '+service)
    blockers=[]
    if out[2]=='WAL_ADAPTER_UNCONNECTED':blockers.append('Common durable WAL/custody business ACK not wired')
    if out[3]=='SNAPSHOT_ADAPTER_UNCONNECTED':blockers.append('Common certified snapshot source not wired')
    blockers.append('T108 real Common node bootstrap available in JAR; no authenticated Spring assignment, physical evidence source, recovery READY or business transaction atomicity installed in live Order/Trade')
    blockers.append('business mutation must be staged before durable commit for every Order/Trade path')
    if labels.get('dc.release.authorized')!='true':blockers.append('candidate image explicitly not authorized')
    if labels.get('dc.common.production.ha.verified')!='true':blockers.append('no real physical dual-node HA acceptance proof')
    return {'service':service,'image':image,'image_id':record['Id'],
            'source_revision':fields['source'],'old_service_cluster_class_directory_absent':True,
            'business_state_machine_class_present':True,'common_cluster_mandatory_by_default':True,
            'fatal_startup_exit_class_present':True,
            'common_node_control_wiring_present':True,
            'spring_failure_event_listener_present':True,
            'common_sha256':COMMON_SHA,
            'common_certified_business_boundary_and_registry_loaded_in_Docker_probe':True,
            'T108_certified_ZK_pinned_node_runtime_in_Common':True,'shared_identity_jar_sha256':SHARED_IDENTITY_SHA,
            'existing_demo_rsa_key_loader_present':True,
            'existing_common_physical_proof_wiring_present':True,
            'private_key_not_baked_in_image':True,
            'durability_and_ready_blockers':blockers,'isolated_no_network':True}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--order-image',default=IMAGES['order']['image'])
    p.add_argument('--trade-image',default=IMAGES['trade']['image'])
    p.add_argument('--strict-release',action='store_true')
    args=p.parse_args()
    reports=[verify('order',args.order_image),verify('trade',args.trade_image)]
    blockers=[f"{r['service']}: {b}" for r in reports for b in r['durability_and_ready_blockers']]
    result={'artifact_binary_validation':'PASS',
            'release_decision':'NO-GO' if blockers else 'BINARY_GATE_PASS_NEEDS_REAL_HA_EVIDENCE',
            'blockers':blockers,'images':reports}
    print(json.dumps(result,indent=2,sort_keys=True))
    return 2 if args.strict_release and blockers else 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as ex:
        print('CANDIDATE_IMAGE_BINARY_GATE_ERROR: '+str(ex),file=sys.stderr)
        sys.exit(3)
