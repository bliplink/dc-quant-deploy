import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/check-md-failover-preflight.py'
spec=importlib.util.spec_from_file_location('md_gate',SCRIPT)
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


def assignments(replicas=('MDSvrB',)):
    return [{'partitionId':'P%03d'%i,'epoch':1,'primary':'MDSvrA' if i%2==0 else 'MDSvrB',
             'replica':'MDSvrB' if i%2==0 else 'MDSvrA',
             'replicas':list(replicas) if i%2==0 else ['MDSvrA'], 'state':'READY'}
            for i in range(256)]


def images():
    return {n:{'image':gate.REQUIRED_IMAGE,'running':True} for n in gate.NODES}

class MdFailoverPreflightTests(unittest.TestCase):
    def test_current_primary_128_128_one_candidate_per_partition_remains_blocked(self):
        outcome=gate.evaluate(assignments(),images())
        self.assertEqual(outcome['primaryCounts'],{'MDSvrA':128,'MDSvrB':128})
        self.assertEqual(outcome['singleReplicaPartitionCount'],256)
        self.assertFalse(outcome['canPromote'])
        self.assertFalse(outcome['canInjectMdPrimaryFault'])
        self.assertEqual(outcome['withoutRecoveryCandidateCount'],0)
        self.assertFalse(any('INSUFFICIENT_CONFIGURED_REPLICA_SLOTS' in b for b in outcome['blockers']))
        self.assertIn('ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',outcome['blockers'])
        self.assertIn('MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED',outcome['blockers'])
    def test_even_full_three_node_placement_cannot_fake_watermark(self):
        rows=assignments()
        for row in rows:
            row['replicas']=[n for n in gate.NODES if n!=row['primary']]
        outcome=gate.evaluate(rows,images())
        self.assertEqual(outcome['singleReplicaPartitionCount'],0)
        self.assertEqual(outcome['decision'],'BLOCKED')
        self.assertIn('ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',outcome['blockers'])
    def test_no_assigned_replica_or_learner_blocks_recovery(self):
        rows=assignments()
        rows[0]['replicas']=[];rows[0]['replica']=None
        outcome=gate.evaluate(rows,images())
        self.assertEqual(outcome['withoutRecoveryCandidateCount'],1)
        self.assertTrue(any('MD_NO_ASSIGNED_RECOVERY_CANDIDATE:1/256' in b
                            for b in outcome['blockers']))

    def test_valid_learner_counts_as_rebuild_candidate_without_extra_md_replica(self):
        rows=assignments()
        rows[0]['replicas']=[];rows[0]['replica']=None
        rows[0]['learners']=['MDSvrC']
        outcome=gate.evaluate(rows,images())
        self.assertEqual(outcome['withoutRecoveryCandidateCount'],0)
        self.assertIn('ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',outcome['blockers'])

    def test_detects_stale_epoch_or_unroutable_state(self):
        rows=assignments();rows[19]['state']='RECOVERING';rows[2]['epoch']=0
        self.assertEqual(gate.evaluate(rows,images())['unreadyPartitions'],2)
    def test_rejects_wrong_replica_and_unreviewed_image(self):
        rows=assignments();rows[0]['replicas']=['MDSvrA','MDSvrC']
        image=images();image['MDSvrC']['image']='unreviewed'
        checks=gate.evaluate(rows,image)['blockers']
        self.assertTrue(any('INVALID_MD_NODE_PLACEMENT' in x for x in checks))
        self.assertTrue(any('UNREVIEWED' in x for x in checks))
    def test_rejects_incomplete_or_duplicate_assignments(self):
        records=assignments()
        content='\n'.join(__import__('json').dumps(x) for x in records)
        self.assertEqual(len(gate.parse_assignments(content)),256)
        with self.assertRaisesRegex(ValueError,'incomplete'):
            gate.parse_assignments(content.rsplit('\n',1)[0])
        records[255]['partitionId']=records[254]['partitionId']
        with self.assertRaisesRegex(ValueError,'duplicate'):
            gate.parse_assignments('\n'.join(__import__('json').dumps(x) for x in records))
    def test_verified_ephemeral_zk_members_not_confused_with_directory(self):
        real='\n'.join(
            '[zk: CONNECTED] %d] get -s /MDTService/%s/%s\n' % (i,n,n)
            + ('ephemeralOwner = 0x123abc' if i<2 else 'ephemeralOwner = 0x0')
            for i,n in enumerate(gate.NODES))
        members=gate.parse_ephemeral_membership(real)
        self.assertTrue(members['MDSvrA'])
        self.assertTrue(members['MDSvrB'])
        self.assertFalse(members['MDSvrC'])
        self.assertIn('MD_EPHEMERAL_MEMBER_NOT_ATTESTED:MDSvrC',
                      gate.evaluate(assignments(),images(),members)['blockers'])
    def test_absent_ephemeral_node_fails_closed_even_when_docker_healthy(self):
        members=gate.parse_ephemeral_membership('[zk: CONNECTED] 0] get -s /MDTService/MDSvrA/MDSvrA\nNode does not exist')
        self.assertFalse(any(members.values()))
        self.assertEqual(len([b for b in gate.evaluate(assignments(),images(),members)['blockers']
                              if 'MD_EPHEMERAL_MEMBER_NOT_ATTESTED' in b]),3)

    def test_explicit_local_immutable_image_lock_avoids_false_image_blocker_but_never_promotes(self):
        image='dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101'
        images_local={node:{'image':image,'running':True} for node in gate.NODES}
        report=gate.evaluate(assignments(),images_local,
                             {node:True for node in gate.NODES},image)
        self.assertEqual(report['expectedImage'],image)
        self.assertEqual(report['decision'],'BLOCKED')
        self.assertFalse(report['canInjectMdPrimaryFault'])
        self.assertFalse(any('UNREVIEWED' in b for b in report['blockers']))
        self.assertIn('ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',report['blockers'])
        with self.assertRaisesRegex(ValueError,'expected image'):
            gate.evaluate(assignments(),images_local,required_image='dc-saas/mdsvr:latest')

    def test_mixed_locked_MD_C_canary_image_reports_real_blockers_not_false_image_alert(self):
        old='dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101'
        canary='dc-saas/mdsvr:cluster-dev-local-md-ha-a5f6063-20261011'
        details={node:{'image':old,'running':True} for node in gate.NODES}
        details['MDSvrC']['image']=canary
        members={node:True for node in gate.NODES}
        rejected=gate.evaluate(assignments(),details,members,old)
        self.assertIn('MD_NODE_UNHEALTHY_OR_UNREVIEWED:MDSvrC',rejected['blockers'])
        verified=gate.evaluate(assignments(),details,members,old,{'MDSvrC':canary})
        self.assertEqual(verified['expectedImagesByNode']['MDSvrC'],canary)
        self.assertFalse(any('UNREVIEWED' in blocker for blocker in verified['blockers']))
        self.assertEqual('BLOCKED',verified['decision'])
        self.assertFalse(verified['canInjectMdPrimaryFault'])
        self.assertIn('ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',verified['blockers'])
        with self.assertRaisesRegex(ValueError,'reviewed'):
            gate.evaluate(assignments(),details,members,old,{'MDSvrC':'dc-saas/mdsvr:latest'})
        with self.assertRaisesRegex(ValueError,'reviewed'):
            gate.evaluate(assignments(),details,members,old,{'MDSvrX':canary})

    def test_exact_docker_image_id_locks_current_local_tag_without_relaxing_primary_gate(self):
        digest='sha256:'+'a'*64
        local={node:{'image':'dc-saas/mdsvr:epoch-refresh-after-subscribe-20261015',
                     'imageId':digest,'running':True} for node in gate.NODES}
        report=gate.evaluate(assignments(),local,{node:True for node in gate.NODES},
                             expected_image_id=digest)
        self.assertEqual(digest,report['expectedImageId'])
        self.assertEqual('BLOCKED',report['decision'])
        self.assertFalse(report['canPromote'])
        self.assertFalse(any('UNREVIEWED' in reason for reason in report['blockers']))
        self.assertIn('ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING',report['blockers'])
        local['MDSvrC']['imageId']='sha256:'+'b'*64
        self.assertIn('MD_NODE_UNHEALTHY_OR_UNREVIEWED:MDSvrC',
                      gate.evaluate(assignments(),local,{node:True for node in gate.NODES},
                                    expected_image_id=digest)['blockers'])
        with self.assertRaisesRegex(ValueError,'exact SHA-256'):
            gate.evaluate(assignments(),local,expected_image_id='sha256:short')

    def test_output_is_read_only_by_design(self):
        self.assertTrue(gate.evaluate(assignments(),images())['readOnly'])
        self.assertNotIn('docker kill',SCRIPT.read_text())
        self.assertNotIn('docker start',SCRIPT.read_text())
if __name__=='__main__': unittest.main()