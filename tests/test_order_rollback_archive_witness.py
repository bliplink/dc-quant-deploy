"""Synthetic CQ fixtures for privacy-safe, fail-closed P246 rollback witness."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1]/'scripts/check-order-rollback-archive-witness.py'
spec=importlib.util.spec_from_file_location('rollback_witness',FILE)
witness=importlib.util.module_from_spec(spec)
spec.loader.exec_module(witness)

def cq(partition,epoch,seq,kind,eventid,payload):
    return ('\t'.join([base64.b64encode(partition.encode()).decode(),str(epoch),str(seq),
           base64.b64encode(kind.encode()).decode(),base64.b64encode(eventid.encode()).decode(),
           '123',base64.b64encode(payload.encode()).decode()])+'\n').encode()

class RollbackWitnessTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        a=self.root/'OrderSvrA'/'journal'/'.archive'/'P246-epoch1-seq578111-42'
        self.arch=a;a.mkdir(parents=True)
        state=cq('P246',1,578109,'STATE_REMOVE','previous-state-1','private-customer-data')
        commit_payload=json.dumps({'version':1,'stateSeq':578109,'stateEpoch':1,
                'stateEventType':'STATE_REMOVE','stateEventId':'previous-state-1'},separators=(',',':'))
        marker=cq('P246',1,578110,'STATE_COMMIT','commit-marker',commit_payload)
        self.state=state;self.marker=marker
        (a/'fixture.cq4').write_bytes(state+marker+cq('P246',1,578111,'STATE_REMOVE','fork','discarded'))
        for node in ('OrderSvrA','OrderSvrB','OrderSvrC'):
            root=self.root/node/'journal'/'P246';root.mkdir(parents=True)
            value=state if node=='OrderSvrC' else state+marker
            (root/'fixture.cq4').write_bytes(value)

    def test_exact_committed_prefix_and_absent_c_marker(self):
        data=witness.inspect(self.root,'P246',1,578109)
        self.assertTrue(data['sameEpochRepairCandidateOnly'])
        self.assertFalse(data['canAutoApplyRepair'])
        self.assertFalse(data['deletionAuthorized'])
        self.assertTrue(data['replicas']['OrderSvrB']['marker']['matchesPrimaryArchive'])
        self.assertFalse(data['replicas']['OrderSvrC']['marker']['present'])
        self.assertTrue(data['replicas']['OrderSvrC']['state']['matchesPrimaryArchive'])
        self.assertNotIn('private-customer-data',json.dumps(data))
        self.assertNotIn('previous-state-1',json.dumps(data))

    def test_different_replica_state_is_rejected(self):
        path=self.root/'OrderSvrC'/'journal'/'P246'/'fixture.cq4'
        path.write_bytes(cq('P246',1,578109,'STATE_REMOVE','other-branch','different'))
        with self.assertRaisesRegex(ValueError,'diverges'):
            witness.inspect(self.root,'P246',1,578109)

    def test_invalid_archive_commit_event_id_is_rejected(self):
        path=self.arch/'fixture.cq4'
        path.write_bytes(self.state+cq('P246',1,578110,'STATE_COMMIT','commit-marker',json.dumps({
            'version':1,'stateSeq':578109,'stateEpoch':1,
            'stateEventType':'STATE_REMOVE','stateEventId':'forged-id'})))
        with self.assertRaisesRegex(ValueError,'does not reference'):
            witness.inspect(self.root,'P246',1,578109)

    def test_ambiguous_archives_are_denied(self):
        (self.arch.parent/'P246-epoch1-seq578111-43').mkdir()
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            witness.inspect(self.root,'P246',1,578109)

    def test_duplicate_seq_is_denied(self):
        path=self.arch/'fixture.cq4'
        path.write_bytes(path.read_bytes()+self.marker)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            witness.inspect(self.root,'P246',1,578109)

    def test_symlink_archive_and_invalid_partition_are_denied(self):
        path=self.arch
        tmp=self.arch.parent/'P246-epoch1-seq578111-43'
        tmp.symlink_to(path,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            witness.inspect(self.root,'P246',1,578109)
        with self.assertRaisesRegex(ValueError,'invalid partition'):
            witness.inspect(self.root,'P../../',1,578109)

if __name__=='__main__':unittest.main()
