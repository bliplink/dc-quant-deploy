"""Read-only Order HA rolling-upgrade gate must fail closed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH=Path(__file__).resolve().parents[1]/'scripts/check-order-rolling-upgrade-preflight.py'
SPEC=importlib.util.spec_from_file_location('order_upgrade_preflight',PATH)
gate=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def records():
    return [{'partitionId':f'P{i:03d}','epoch':1,'state':'READY',
             'primary':'OrderSvrA' if i%2==0 else 'OrderSvrB',
             'replicas':['OrderSvrB','OrderSvrC'] if i%2==0 else ['OrderSvrA','OrderSvrC']}
            for i in range(256)]


def good_configs():
    return {node:dict(gate.MANDATORY_CONFIG) for node in gate.NODES}


def good_images():
    return {node:{'running':True,'image':'ghcr.io/bliplink/ordersvr:sha-pinned'}
            for node in gate.NODES}


def good_snapshots():
    return {'snapshotFilesInspected':768,'missingSnapshotPartitions':[],
            'divergentPartitions':[],'totalPartitions':256}


class OrderUpgradeSafetyTests(unittest.TestCase):
    def test_static_green_cannot_replace_writer_drain_and_watermark(self):
        result=gate.evaluate(records(),good_configs(),good_snapshots(),good_images(),0,45)
        self.assertEqual('BLOCKED',result['decision'])
        self.assertFalse(result['canRestartOrderNodes'])
        self.assertFalse(result['canEnableP246Repair'])
        self.assertEqual({'OrderSvrA':128,'OrderSvrB':128,'OrderSvrC':0},result['primaryCounts'])
        self.assertEqual(256,result['zkReadyAssignments'])
        self.assertIn('WRITE_DRAIN_NOT_ATTESTED',result['blockers'])
        self.assertIn('PROJECTION_WATERMARKS_NOT_ATTESTED',result['blockers'])

    def test_live_p246_disk_and_recovery_errors_are_blockers(self):
        snaps=good_snapshots();snaps['divergentPartitions']=['P246']
        r=gate.evaluate(records(),good_configs(),snaps,good_images(),616,91.5)
        self.assertIn('SNAPSHOT_MISMATCH:P246',r['blockers'])
        self.assertIn('ACTIVE_RECOVERY_ERRORS:616',r['blockers'])
        self.assertIn('DISK_PRESSURE:91.5%',r['blockers'])
        self.assertFalse(r['canRestartOrderNodes'])

    def test_missing_or_duplicate_assignment_is_rejected(self):
        lines='\n'.join(json.dumps(x) for x in records())
        self.assertEqual(256,len(gate.decode_assignments(lines)))
        with self.assertRaisesRegex(ValueError,'duplicate|missing'):
            gate.decode_assignments(lines+'\n'+json.dumps(records()[0]))
        with self.assertRaisesRegex(ValueError,'duplicate|missing'):
            gate.decode_assignments('\n'.join(json.dumps(x) for x in records()[:-1]))

    def test_bad_replica_topology_invalid_epoch_and_not_ready_block(self):
        rows=records();rows[0]['replicas']=['OrderSvrB','OrderSvrB']
        rows[1]['epoch']=0;rows[2]['state']='READY_IN_ZK_ONLY'
        r=gate.evaluate(rows,good_configs(),good_snapshots(),good_images(),0,50)
        self.assertIn('INVALID_REPLICA_TOPOLOGY:P000',r['blockers'])
        self.assertIn('INVALID_EPOCH:P001',r['blockers'])
        self.assertIn('ZOOKEEPER_ASSIGNMENTS_NOT_READY:P002',r['blockers'])

    def test_global_archive_repair_misconfiguration_is_blocked(self):
        cfg=good_configs();cfg['OrderSvrA']['order.cluster.replication.archivedCommitRepairEnabled']='true'
        cfg['OrderSvrB']['order.cluster.replication.consistencyMode']='ASYNC_BATCHED'
        r=gate.evaluate(records(),cfg,good_snapshots(),good_images(),0,50)
        self.assertIn('ARCHIVE_REPAIR_ALREADY_ENABLED:OrderSvrA',r['blockers'])
        self.assertTrue(any(x.startswith('UNEXPECTED_SYNC_POLICY:OrderSvrB') for x in r['blockers']))

    def test_unavailable_node_or_runtime_logs_block(self):
        imgs=good_images();imgs['OrderSvrC']['running']=False
        r=gate.evaluate(records(),good_configs(),good_snapshots(),imgs,None,None)
        self.assertIn('NODE_NOT_RUNNING:OrderSvrC',r['blockers'])
        self.assertIn('RECENT_RUNTIME_RECOVERY_LOGS_UNAVAILABLE',r['blockers'])
        self.assertIn('DISK_HEADROOM_UNKNOWN',r['blockers'])

    def test_snapshot_fingerprint_handles_broken_and_divergent_state(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for node in gate.NODES:
                dest=root/node/'snapshot'/'P000'/'snapshot.json';dest.parent.mkdir(parents=True)
                dest.write_text(json.dumps({'partitionId':'P000','epoch':1,'books':[]}))
            rows=[records()[0]]
            one=gate.compare_snapshots(rows,root)
            self.assertEqual(3,one['snapshotFilesInspected'])
            self.assertEqual([],one['divergentPartitions'])
            (root/'OrderSvrC'/'snapshot'/'P000'/'snapshot.json').write_text(json.dumps({'partitionId':'P000','epoch':1,'books':[{'orders':[]}]}))
            two=gate.compare_snapshots(rows,root)
            self.assertEqual(['P000'],two['divergentPartitions'])
            (root/'OrderSvrB'/'snapshot'/'P000'/'snapshot.json').unlink()
            three=gate.compare_snapshots(rows,root)
            self.assertEqual(['P000'],three['missingSnapshotPartitions'])

    def test_invalid_config_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'real.properties';p.write_text('order.cluster.replication.required=true')
            alias=root/'config.properties';alias.symlink_to(p)
            with self.assertRaisesRegex(ValueError,'unsafe'):
                gate.read_config(alias)


if __name__=='__main__':unittest.main()
