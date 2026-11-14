import copy
import json
import unittest
from t554_execution_archive_audit import audit


class ArchiveAuditTest(unittest.TestCase):
    def sample(self, flag='1'):
        expected, rows, views = {}, [], []
        for index, identity in enumerate(['E1', 'E2']):
            expected[identity] = dict(location='ABC123', order_id='O'+str(index), user_id='U'+str(index),
                security_id='BTCUSDT', side='Buy', last_qty='.1', last_px='10', demo=flag,
                trade_partition='P001', match_key='M1', request_ids=['PAIR:one', 'GROUP:M1'])
            report = dict(Location='ABC123', OrderID='O'+str(index), UserID='U'+str(index),
                SecurityID='BTCUSDT', Side='Buy', LastQty='.1', LastPx='10', Demo=flag,
                ExecType='Trade', ExecID=identity)
            payload = json.dumps(dict(report=report, result=dict(code=0, info1='-.001', info2='0')))
            rows.append(dict(request_id='PAIR:one', source_type='TRADE_ATOMIC_MATCH_PAIR_PREPARED',
                operation='UPSERT', entity_key='ABC123\x1f'+identity, payload=payload,
                partition_id='P001', source_epoch=2, journal_seq=3, mutation_index=index))
            views.append(dict(exec_id=identity, **{k:expected[identity][k] for k in
                ['order_id', 'user_id', 'security_id', 'side', 'last_qty', 'last_px']},
                fee='-.001', realized_pnl='0', currency=''))
        event = dict(location='ABC123', requestId='PAIR:one', sourceType='TRADE_ATOMIC_MATCH_PAIR_PREPARED',
            mutations=[dict(entityType='DEDUPE_RESULT', operation=r['operation'], entityKey=r['entity_key'],
                            payload=r['payload']) for r in rows])
        for row in rows:
            row['event_payload'] = json.dumps(event)
        return expected, rows, views

    def test_filtered_demo_requires_all_committed_executions_but_no_customer_view_rows(self):
        expected, rows, views = self.sample()
        result = audit(expected, rows, [], False)
        self.assertTrue(result['passed'])
        self.assertEqual((2, 0, 1), (result['archived_client_executions'],
            result['materialized_client_executions'], result['original_match_commits']))
        self.assertFalse(audit(expected, rows[:-1], [], False)['passed'])
        self.assertFalse(audit(expected, rows, views, False)['passed'])

    def test_real_orders_and_enabled_demo_still_require_complete_economic_views(self):
        for flag, policy in [('0', False), ('1', True)]:
            expected, rows, views = self.sample(flag)
            self.assertTrue(audit(expected, rows, views, policy)['passed'])
            self.assertFalse(audit(expected, rows, [], policy)['passed'])
            views[0]['fee'] = '0'
            self.assertFalse(audit(expected, rows, views, policy)['passed'])

    def test_duplicate_archive_and_separate_commits_cannot_impersonate_one_atomic_match(self):
        expected, rows, views = self.sample()
        self.assertFalse(audit(expected, rows + [copy.deepcopy(rows[0])], [], False)['passed'])
        rows[1]['journal_seq'] = 4
        result = audit(expected, rows, [], False)
        self.assertIn('ORIGINAL_MATCH_ATOMIC_COMMIT_BOUNDARIES_DIFFER', result['violations'])

    def test_original_identity_amounts_and_source_link_must_all_match(self):
        for field, value in [('request_id', 'PAIR:other'), ('partition_id', 'P002'),
                             ('entity_key', 'ABC123\x1fE2'), ('operation', 'DELETE')]:
            expected, rows, views = self.sample()
            rows[0][field] = value
            self.assertFalse(audit(expected, rows, [], False)['passed'])
        for field, value in [('LastQty', '.2'), ('Demo', '0'), ('UserID', 'different')]:
            expected, rows, views = self.sample()
            payload = json.loads(rows[0]['payload']);payload['report'][field] = value
            rows[0]['payload'] = json.dumps(payload)
            event = json.loads(rows[0]['event_payload']);event['mutations'][0]['payload'] = rows[0]['payload']
            for row in rows:
                row['event_payload'] = json.dumps(event)
            self.assertFalse(audit(expected, rows, [], False)['passed'])

    def test_missing_or_nonfinite_financial_amounts_are_not_zero(self):
        for value in [None, 'NaN', 'Infinity']:
            expected, rows, views = self.sample()
            payload = json.loads(rows[0]['payload']);payload['result']['info1'] = value
            rows[0]['payload'] = json.dumps(payload)
            event = json.loads(rows[0]['event_payload']);event['mutations'][0]['payload'] = rows[0]['payload']
            for row in rows:
                row['event_payload'] = json.dumps(event)
            self.assertFalse(audit(expected, rows, [], False)['passed'])


if __name__ == '__main__':
    unittest.main()
