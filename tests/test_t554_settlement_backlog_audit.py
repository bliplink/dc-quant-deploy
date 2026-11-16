import runpy
from pathlib import Path
import unittest
import json
import tempfile
from unittest.mock import patch

audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/verify-mac-demo-settlement-backlog.py'))['audit']
audit_all=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/verify-mac-demo-settlement-backlog.py'))['audit_all_partitions']


class SettlementBacklogAuditTest(unittest.TestCase):
    def complete_partition_observation(self):
        manifest={f'P{i:03d}':{'primary':'OrderSvrA' if i<128 else 'OrderSvrB','epoch':2}
                  for i in range(256)}
        texts=['','']
        for partition,row in manifest.items():
            slot=0 if row['primary']=='OrderSvrA' else 1
            texts[slot]+=f"PARTITION_OWNER\t{partition}\t{row['primary']}\t2\n"
        return manifest,texts

    def test_custom_product_pending_outside_btc_partition_is_counted(self):
        manifest,texts=self.complete_partition_observation()
        texts[0]+='MATCH\tGG9FPW\tP021\ttrue\t200\t2\t4\n'
        texts[1]+='MATCH\tGG9FPW\tP200\tfalse\t31000\t2\t8\n'
        result=audit_all(texts,['GG9FPW'],manifest)
        self.assertFalse(result['passed'])
        self.assertEqual(256,result['observed_primary_partitions'])
        self.assertEqual(1,result['locations']['GG9FPW']['aged_financial_unsettled'])
        self.assertEqual(1,result['locations']['GG9FPW']['local_final_replication_pending'])

    def test_incomplete_stale_duplicate_and_wrong_source_fail_closed(self):
        manifest,texts=self.complete_partition_observation()
        cases=[['',texts[1]],
               [texts[0].replace('OrderSvrA\t2','OrderSvrA\t3',1),texts[1]],
               [texts[0]+'PARTITION_OWNER\tP000\tOrderSvrA\t2\n',texts[1]],
               [texts[0]+'MATCH\tGG9FPW\tP200\tfalse\t31000\t2\t8\n',texts[1]],
               [texts[0],texts[1]+'MATCH\tOTHER1\tP200\tfalse\t31000\t2\t8\n'],
               [texts[0],texts[1]+'MATCH\tGG9FPW\tP200\tfalse\t31000\t2\t8\n'*2]]
        for case in cases:
            with self.subTest(case=cases.index(case)),self.assertRaises(ValueError):
                audit_all(case,['GG9FPW'],manifest)

    def test_order_only_replay_record_is_visible_and_not_financially_unsettled(self):
        manifest,texts=self.complete_partition_observation()
        texts[0]+='ORDER_ONLY_RETAINED\tGG9FPW\tP053\tBTC003USDT\t3000000\t2\t6\n'
        result=audit_all(texts,['GG9FPW'],manifest)
        self.assertTrue(result['passed'])
        self.assertFalse(result['all_business_delivery_records_retired'])
        self.assertEqual(1,len(result['order_only_retained_delivery_records']))
        self.assertEqual(0,result['locations']['GG9FPW']['financial_unsettled'])
        texts[0]+='MATCH\tGG9FPW\tP053\tfalse\t3000000\t2\t6\n'
        with self.assertRaises(ValueError):audit_all(texts,['GG9FPW'],manifest)

    def test_financially_unsettled_match_is_visible_even_if_order_is_filled(self):
        result=audit(['MATCH\tGG9FPW\tP021\tfalse\t31000\t7\t4\nOWNER\tGG9FPW\tP021\n'],['GG9FPW'])
        self.assertFalse(result['passed'])
        self.assertEqual(1,result['locations']['GG9FPW']['aged_financial_unsettled'])

    def test_current_matches_and_separate_local_replication_deadline(self):
        text='MATCH\tGG9FPW\tP021\tfalse\t200\t7\t4\nMATCH\tGG9FPW\tP021\ttrue\t31000\t7\t5\nOWNER\tGG9FPW\tP021\n'
        self.assertTrue(audit([text],['GG9FPW'])['passed'])
        self.assertFalse(audit([text.replace('31000','301000')],['GG9FPW'])['passed'])

    def test_missing_duplicate_and_wrong_owner_observations_fail_closed(self):
        for text in ['', 'OWNER\tGG9FPW\tP021\nOWNER\tGG9FPW\tP021\n',
                     'MATCH\tGG9FPW\tP020\tfalse\t10\t7\t4\nOWNER\tGG9FPW\tP021\n']:
            with self.assertRaises(ValueError):audit([text],['GG9FPW'])

    def test_stopped_original_robot_backlog_still_blocks_new_pressure(self):
        capacity=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/verify-mac-demo-robot-capacity.py'))
        require=capacity['require_robot_settlements_ready']
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'business-baseline-robots-20261115.json').write_text(json.dumps({'locations':['GG9FPW']}))
            observed=[]
            def read(root,locations):
                observed.extend(locations)
                return {'passed':False,'evidence':'retained-proof.json'}
            with patch.dict(require.__globals__,{'demo_tenants':lambda:{},'audit_settlement_backlog':read}):
                with self.assertRaisesRegex(RuntimeError,'Aged original Robot settlements'):
                    require(root)
            self.assertEqual(['GG9FPW'],observed)


if __name__=='__main__':unittest.main()
