import runpy
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-robot-capacity.py'))
AUDIT = CAPACITY['audit_tape_immediate_terminals']


class TapeTerminalAuditTest(unittest.TestCase):
    def check(self, orders):
        sql = Mock(side_effect=[[['ABC123', 'TAPEUSER']], [['fixture-live-session']]])
        request = Mock(return_value={'code': 0, 'data': orders})
        with patch.dict(AUDIT.__globals__['PRODUCT'], readonly_sql=sql, call=request):
            result = AUDIT({'ABC123'})
        self.assertNotIn('fixture-live-session', repr(result))
        return result

    @staticmethod
    def order(age, tif='IOC', terminal='RobotSvr-Tape'):
        return {'OrderID': 'fixture-order', 'ClOrdID': 'fixture-request', 'OrdStatus': 'New',
                'Terminal': terminal, 'TimeInForce': tif,
                'UpdateTime': (datetime.now() - timedelta(seconds=age)).strftime('%Y-%m-%d %H:%M:%S.%f')}

    def test_aged_new_ioc_fails_even_if_aggregate_fill_and_financial_counts_are_healthy(self):
        result = self.check([self.order(60)])
        self.assertFalse(result['passed'])
        self.assertEqual('fixture-order', result['aged_nonterminal_orders'][0]['order_id'])

    def test_a_just_submitted_ioc_is_given_its_existing_bounded_completion_window(self):
        self.assertTrue(self.check([self.order(1)])['passed'])

    def test_resting_gtc_and_the_market_maker_are_not_misclassified_as_stuck_tape_orders(self):
        self.assertTrue(self.check([self.order(600, tif='GTC'), self.order(600, terminal='RobotSvr')])['passed'])

    def test_missing_tape_account_cannot_be_assumed_to_have_no_open_orders(self):
        with patch.dict(AUDIT.__globals__['PRODUCT'], readonly_sql=Mock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError, 'exact Robot Tape accounts'):
                AUDIT({'ABC123'})

    def test_an_incomplete_bounded_query_does_not_report_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'complete bounded query'):
            self.check([self.order(1)] * 100)

    def test_failed_authorized_read_never_looks_like_an_empty_account(self):
        sql = Mock(side_effect=[[['ABC123', 'TAPEUSER']], [['fixture-expired-session']]])
        with patch.dict(AUDIT.__globals__['PRODUCT'], readonly_sql=sql,
                        call=Mock(return_value={'code': 7004})):
            with self.assertRaisesRegex(RuntimeError, 'Live Tape account open-order query failed'):
                AUDIT({'ABC123'})


if __name__ == '__main__':
    unittest.main()
