"""Synthetic readonly recovery evidence: never authorizes installation/READY."""
import base64
import json
from pathlib import Path
import tempfile
import unittest

from audit_trade_committed_prefix_readonly import audit, audit_partition


def record(part, seq, kind, event_id, payload):
    b64=lambda x:base64.b64encode(x.encode()).decode()
    return (b64(part)+"\t1\t"+str(seq)+"\t"+b64(kind)+"\t"+
            b64(event_id)+"\t1792040100000\t"+b64(json.dumps(payload,sort_keys=True)))


class CommittedPrefixEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.part='P190'
        source=self.root/'TradeSvrA'
        replica=self.root/'TradeSvrB'
        (source/'snapshot'/self.part).mkdir(parents=True)
        (source/'journal'/self.part).mkdir(parents=True)
        self.archive=source/'journal'/'.archive'/'P190-epoch1-seq5-example'
        self.archive.mkdir(parents=True)
        self.replica=replica/'journal'/self.part
        self.replica.mkdir(parents=True)
        (source/'snapshot'/self.part/'latest.json').write_text(json.dumps({
            'partitionId':self.part,'epoch':1,'snapshotSeq':4,
            'committedStateSeq':3,'committedStateEpoch':1,'locations':['TEST']}))
        (source/'journal'/self.part/'baseline.properties').write_text(
            'epoch=1\nbaselineSeq=4\ncommitMarkerSeq=4\ncommittedStateSeq=3\n')
        self.rows=[record(self.part,1,'STATE_BATCH','state-1',{'amount':1}),
                   record(self.part,2,'STATE_COMMIT','state-1:commit',
                          {'stateSeq':1,'stateEpoch':1,'stateEventId':'state-1'}),
                   record(self.part,3,'STATE_BATCH','state-3',{'amount':2}),
                   record(self.part,4,'STATE_COMMIT','state-3:commit',
                          {'stateSeq':3,'stateEpoch':1,'stateEventId':'state-3'}),
                   record(self.part,5,'STATE_BATCH','retry',{'amount':5})]
        self.write(self.rows,self.rows[:-1]+[record(self.part,5,'STATE_BATCH','earlier',{'amount':3})])

    def tearDown(self): self.tmp.cleanup()

    def write(self, source, replica):
        # Binary framing deliberately starts with a base64-like header byte.
        # A frame reader must recover exactly the encoded JSON envelope.
        (self.archive/'example.cq4').write_bytes((b'\x00'.join(x.encode()+b'\x11' for x in source)))
        (self.replica/'example.cq4').write_bytes((b'\x00'.join(x.encode()+b'\x11' for x in replica)))

    def test_complete_prefix_identical_with_divergent_uncommitted_tail(self):
        out=audit(self.root,[self.part])
        self.assertTrue(out['allLocalCommittedPrefixesEqual'])
        self.assertFalse(out['authorizesReady'])
        self.assertFalse(out['authorizesReplicaInstall'])
        self.assertFalse(out['independentPhysicalQuorumVerified'])
        row=out['rows'][0]
        self.assertEqual(4,row['sourceCommittedRecords'])
        self.assertEqual(4,row['replicaCommittedRecords'])
        self.assertTrue(row['nextUncommittedRawTextConflicts'])

    def test_committed_record_mismatch_never_authorizes(self):
        wrong=self.rows.copy()
        wrong[2]=record(self.part,3,'STATE_BATCH','state-3',{'amount':99})
        self.write(self.rows,wrong)
        out=audit(self.root,[self.part])
        self.assertFalse(out['allLocalCommittedPrefixesEqual'])
        self.assertFalse(out['rows'][0]['committedPrefixCompleteAndEqual'])
        self.assertIsNone(out['rows'][0]['committedPrefixSha256'])

    def test_missing_replica_record_fails_closed(self):
        self.write(self.rows,[self.rows[0],self.rows[1],self.rows[3]])
        out=audit(self.root,[self.part])
        self.assertFalse(out['allLocalCommittedPrefixesEqual'])
        self.assertEqual(3,out['rows'][0]['replicaCommittedRecords'])

    def test_missing_commit_boundary_rejected(self):
        path=self.root/'TradeSvrA'/'journal'/self.part/'baseline.properties'
        path.write_text(path.read_text().replace('commitMarkerSeq=4','commitMarkerSeq=3'))
        with self.assertRaisesRegex(ValueError,'disagreement'):
            audit_partition(self.root,self.part)

    def test_unsafe_partition_rejected(self):
        with self.assertRaisesRegex(ValueError,'partition'):
            audit_partition(self.root,'../P190')


if __name__=='__main__': unittest.main()
