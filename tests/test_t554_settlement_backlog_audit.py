import runpy
from pathlib import Path
import unittest
import json
import tempfile
from unittest.mock import patch

audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/verify-mac-demo-settlement-backlog.py'))['audit']


class SettlementBacklogAuditTest(unittest.TestCase):
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
