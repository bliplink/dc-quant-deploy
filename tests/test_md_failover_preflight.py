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
    def test_current_primary_128_128_no_legal_quorum_and_remains_blocked(self):
        outcome=gate.evaluate(assignments(),images())
        self.assertEqual(outcome['primaryCounts'],{'MDSvrA':128,'MDSvrB':128})
        self.assertEqual(outcome['singleReplicaPartitionCount'],256)
        self.assertFalse(outcome['canPromote'])
        self.assertFalse(outcome['canInjectMdPrimaryFault'])
        self.assertTrue(any('INSUFFICIENT' in b for b in outcome['blockers']))
    def test_even_full_three_node_placement_cannot_fake_watermark(self):
        rows=assignments()
        for row in rows:
            row['replicas']=[n for n in gate.NODES if n!=row['primary']]
        outcome=gate.evaluate(rows,images())
        self.assertEqual(outcome['singleReplicaPartitionCount'],0)
        self.assertEqual(outcome['decision'],'BLOCKED')
        self.assertIn('MD_DURABLE_SOURCE_WATERMARK_PROOFS_MISSING',outcome['blockers'])
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
    def test_output_is_read_only_by_design(self):
        self.assertTrue(gate.evaluate(assignments(),images())['readOnly'])
        self.assertNotIn('docker kill',SCRIPT.read_text())
        self.assertNotIn('docker start',SCRIPT.read_text())
if __name__=='__main__': unittest.main()
