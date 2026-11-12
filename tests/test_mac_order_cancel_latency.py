import importlib.util
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-order-cancel-capacity.py'
SPEC = importlib.util.spec_from_file_location('mac_order_cancel_capacity', SCRIPT)
CAPACITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPACITY)


class OrderCancelLatencyTest(unittest.TestCase):
    def test_controlled_robot_stop_waits_past_bootstrap_enable_and_owner_release(self):
        read = CAPACITY.PRODUCT['readonly_sql']
        with patch.dict(CAPACITY.PRODUCT, readonly_sql=Mock(side_effect=[
                [['PENDING']], [['COMPLETE']], [['0', 'original-owner']], [['0', '']]])), \
                patch.object(CAPACITY.time, 'sleep') as sleep:
            def stop(service, method, request, token):
                self.assertEqual(2, CAPACITY.PRODUCT['readonly_sql'].call_count)
                self.assertEqual(('ManagerSvr', 'robotControl', 'STOP', 'fixture-token'),
                                 (service, method, request['action'], token))

            with patch.object(CAPACITY, 'api', side_effect=stop) as api:
                proof = CAPACITY.stop_trial_robot_after_bootstrap('ABC123', 'fixture-token')
            api.assert_called_once()
            self.assertEqual(2, sleep.call_count)
            self.assertTrue(proof['bootstrap_complete_before_stop'])
            self.assertTrue(proof['disabled_and_owner_released'])
        self.assertIs(read, CAPACITY.PRODUCT['readonly_sql'])

    def test_incomplete_bootstrap_never_issues_a_premature_stop(self):
        with patch.dict(CAPACITY.PRODUCT, readonly_sql=Mock(return_value=[['PENDING']])), \
                patch.object(CAPACITY.time, 'monotonic', side_effect=[0, 181]), \
                patch.object(CAPACITY, 'api') as api:
            with self.assertRaisesRegex(RuntimeError, 'bootstrap did not complete'):
                CAPACITY.stop_trial_robot_after_bootstrap('ABC123', 'fixture-token')
        api.assert_not_called()

    def test_controlled_trader_can_retain_its_own_password_for_long_fault_exercises(self):
        def api(server, method, content, token=None):
            return {'user_id': 'fixture-user'} if method == 'tenantUserRegistration' else {'token': 'fixture-token'}

        with patch.object(CAPACITY, 'api', side_effect=api) as request:
            self.assertEqual(('ABC123', 'fixture-user', 'fixture-token'),
                             CAPACITY.new_trader('ABC123', 'BTC003USDT', 'ORDER_ONLY', 'fixture', 0,
                                                 'caller-owned-fixture-password'))
        for call in request.call_args_list:
            self.assertEqual('caller-owned-fixture-password', call.args[2]['password'])

    def test_controlled_products_accepts_a_caller_owned_admin_password(self):
        def api(server, method, content, token=None):
            if method == 'tenantApplication':
                return {'status': 'APPROVED', 'approved_location': 'ABC123'}
            if method == 'SYS.ATS.LOGIN':
                return {'token': 'fixture-admin-token'}
            if method == 'tenantApiKeyAdmin':
                return {'api_key': 'fixture-key', 'secret_key': 'fixture-secret'}
            if method == 'queryPublicMarket':
                return {'ticker': {'MarkPrice': '90001'}}
            return {}

        report = {}
        admin_session = {}
        with patch.object(CAPACITY, 'api', side_effect=api) as request, \
                patch.object(CAPACITY, 'Thread'), \
                patch.dict(CAPACITY.PRODUCT, signed_login=lambda *args: {'token': 'fixture-broker-token'},
                           call=lambda *args: {'code': 0}):
            with CAPACITY.controlled_products('fixture', report, 'caller-owned-fixture-password',
                                              admin_session) as (location, products):
                self.assertEqual('ABC123', location)
                self.assertEqual(2, len(products))
                self.assertEqual({'token': 'fixture-admin-token'}, admin_session)
        self.assertEqual('caller-owned-fixture-password', request.call_args_list[0].args[2]['admin_password'])
        self.assertTrue(report['price_source']['broker_key_deleted'])
        self.assertNotIn('fixture-admin-token', repr(report))

    def test_observed_states_include_the_wait_after_http_ack(self):
        now = [0.0]

        def acknowledge(*arguments):
            now[0] += 0.020

        def observe(trader, symbol, client_order_id, present):
            now[0] += 0.030 if present else 0.040
            return 'order-1' if present else None

        def cancel(*arguments):
            now[0] += 0.030

        with patch.object(CAPACITY.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(CAPACITY, 'api', side_effect=acknowledge), \
                patch.object(CAPACITY, 'await_order', side_effect=observe), \
                patch.object(CAPACITY, 'cancel', side_effect=cancel):
            records = CAPACITY.worker(('ABC123', 'user-1', 'fixture-token'),
                                      'BTCUSDT', '45000', 'fixture', 0, 0.100, Event())

        self.assertEqual(1, len(records))
        self.assertTrue(records[0]['passed'])
        self.assertEqual(20.0, records[0]['place_ack_ms'])
        self.assertEqual(50.0, records[0]['place_new_ms'])
        self.assertEqual(30.0, records[0]['cancel_ack_ms'])
        self.assertEqual(70.0, records[0]['cancel_absent_ms'])
        self.assertEqual(120.0, records[0]['cycle_ms'])


if __name__ == '__main__':
    unittest.main()
