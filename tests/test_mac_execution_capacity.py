import ast
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1]
                              / 'scripts/verify-mac-demo-execution-capacity.py'))


class ExecutionCapacityTest(unittest.TestCase):
    def test_ambiguous_cancel_is_rechecked_before_retry(self):
        from types import SimpleNamespace
        cancel = CAPACITY['cancel_remaining_benchmark_orders']
        attempts = []
        def timeout_after_send(*args, **kwargs):
            attempts.append(args)
            raise TimeoutError()
        snapshots = iter([[{'ClOrdID': 'T554EXEC-run-MAKER', 'OrderID': 'm'}], []])
        with patch.dict(CAPACITY['CANCEL'], open_orders=lambda *args: next(snapshots)), \
                patch.object(cancel.__globals__['time'], 'sleep'):
            cancel(SimpleNamespace(cancel_order=timeout_after_send), ('tenant', 'user', 'token'), 'BTC', 'run')
        self.assertEqual([('BTC', 'm')], attempts)

    def test_cleanup_checks_entire_page_before_cancelling(self):
        from types import SimpleNamespace
        rows = [{'ClOrdID': 'T554EXEC-run-MAKER', 'OrderID': 'own'},
                {'ClOrdID': 'outside', 'OrderID': 'other'}]
        with patch.dict(CAPACITY['CANCEL'], open_orders=lambda *args: rows):
            with self.assertRaisesRegex(ValueError, 'outside'):
                CAPACITY['cancel_remaining_benchmark_orders'](
                    SimpleNamespace(cancel_order=lambda *a, **k: self.fail()), ('tenant', 'user', 'token'), 'BTC', 'run')

    def test_offered_load_is_bounded_by_funded_single_maker_capacity(self):
        source = Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-execution-capacity.py'
        tree = ast.parse(source.read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        guard = next(node for node in main.body if isinstance(node, ast.If))
        condition = compile(ast.Expression(guard.test), 'actual-client-capacity-admission', 'eval')
        for rate, seconds, rejected in [(1, 60, False), (10, 60, False), (15, 60, False),
                                        (3, 300, False), (15, 61, False), (50, 60, False), (100, 60, False),
                                        (20, 300, False), (100.01, 60, True), (100, 61, True),
                                        (20, 301, True), (0, 60, True), (15, 59, True)]:
            with self.subTest(rate=rate, seconds=seconds):
                self.assertEqual(rejected, eval(condition, {'args': SimpleNamespace(rate=rate, seconds=seconds)}))

    def test_funding_uses_normal_cash_in_and_preserves_default_callers(self):
        create = CAPACITY['CANCEL']['new_trader']
        for amount in [None, CAPACITY['FUNDING']]:
            expected = CAPACITY['Decimal']('10000') if amount is None else amount
            calls = []

            def api(service, method, payload, token=None):
                calls.append((service, method, payload, token))
                return {'user_id': 'test-user', 'token': 'test-token'}

            with patch.dict(create.__globals__, api=api, balances=lambda location, user: [[str(expected)]]):
                options = {} if amount is None else {'funding_amount': amount}
                self.assertEqual(('TEST01', 'test-user', 'test-token'),
                                 create('TEST01', 'BTC004USDT', 'TRADE', 'fixture', 0,
                                        password='test-password', **options))
            cash = [call for call in calls if call[1] == 'cashIn']
            self.assertEqual(1, len(cash))
            self.assertEqual(str(expected), cash[0][2]['Amount'])
            self.assertEqual('test-token', cash[0][3])
        maximum_notional = CAPACITY['QUANTITY'] * 6001 * CAPACITY['Decimal'](CAPACITY['PRICE'])
        self.assertLess(maximum_notional * CAPACITY['Decimal']('0.11'), CAPACITY['FUNDING'])
        self.assertLess(CAPACITY['QUANTITY'] * 6001, 10)

    def test_invalid_funding_fails_before_account_creation(self):
        create = CAPACITY['CANCEL']['new_trader']
        for amount in ['0', '-1', '100001', 'NaN', 'Infinity']:
            with self.subTest(amount=amount), patch.dict(create.__globals__, api=lambda *args: self.fail('created account')):
                with self.assertRaises(ValueError):
                    create('TEST01', 'BTC004USDT', 'TRADE', 'fixture', 0, funding_amount=amount)

    def test_only_actual_execution_reports_count_as_fills(self):
        extract = CAPACITY['execution_reports']
        final = {'ExecType': 'Trade', 'ExecID': 'actual-execution', 'OrdStatus': 'Filled'}
        self.assertEqual([final], extract([{'code': 0}, final, {'ExecType': 'New'}, None]))
        self.assertEqual([final], extract(CAPACITY['json'].dumps([final])))
        for unrelated in ['not-json', {'ExecType': 'Trade'}, {'code': 0}, None, 1]:
            self.assertEqual([], extract(unrelated))

    def test_latency_summaries_preserve_missing_final_samples(self):
        rows = [{'ack_ms': 10, 'client_fill_ms': 21}, {'ack_ms': 12}]
        self.assertEqual(2, CAPACITY['summary_ms'](rows, 'ack_ms')['samples'])
        fills = CAPACITY['summary_ms'](rows, 'client_fill_ms')
        self.assertEqual(1, fills['samples'])
        self.assertEqual(21, fills['p99'])
        self.assertIsNone(CAPACITY['summary_ms']([], 'client_fill_ms')['p99'])

    def test_matrix_product_validation_precedes_tenant_creation(self):
        control = CAPACITY['CANCEL']['controlled_products']
        for products in [[], [('TRADE', 'BTC005USDT')] * 2, [('INVALID', 'BTC005USDT')],
                         [('TRADE', 'BTC005USDT')] * 17]:
            with self.subTest(products=products), patch.dict(control.__wrapped__.__globals__,
                    api=lambda *args: self.fail('Created tenant before invalid product rejection')):
                with self.assertRaises(ValueError), control('fixture', {}, products=products):
                    self.fail('Invalid product layout was admitted')

    def test_matrix_cleanup_cancels_only_its_actual_symbol(self):
        calls = []
        client = SimpleNamespace(session=SimpleNamespace(token='current'),
                                 close_stream=lambda **kwargs: None,
                                 cancel_order=lambda symbol, order, **kwargs: calls.append((symbol, order)))
        accounts = [{'client': client, 'trader': ('TEST01', 'user', 'original'),
                     'key': 'test-key', 'symbol': 'BTC005USDT', 'order_attempted': True}]
        pending = [[{'ClOrdID': 'T554EXEC-fixture-MAKER', 'OrderID': 'order'}], []]
        def open_orders(trader, symbol):
            self.assertEqual('BTC005USDT', symbol)
            return pending.pop(0)
        report = {}
        with patch.dict(CAPACITY['CANCEL'], open_orders=open_orders,
                        await_order=lambda trader, symbol, *args: self.assertEqual('BTC005USDT', symbol)), \
                patch.dict(CAPACITY['CANCEL']['PRODUCT'], call=lambda *args: {'code': 0}):
            CAPACITY['cleanup_accounts'](accounts, 'TEST01', 'fixture', report)
        self.assertEqual([('BTC005USDT', 'order')], calls)
        self.assertNotIn('cleanup_errors', report)

    def test_controlled_multi_product_setup_registers_and_checks_each_real_symbol(self):
        control = CAPACITY['CANCEL']['controlled_products']
        wanted = (('TRADE', 'BTC004USDT'), ('TRADE', 'BTC005USDT'))
        calls = []
        def api(service, method, content, token=None):
            calls.append((service, method, content))
            if method == 'tenantApplication': return {'status': 'APPROVED', 'approved_location': 'TEST01'}
            if method == 'SYS.ATS.LOGIN': return {'token': 'fixture-admin'}
            if method == 'tenantApiKeyAdmin': return {'api_key': 'fixture-key', 'secret_key': 'fixture-secret'}
            if method == 'queryPublicMarket': return {'ticker': {'MarkPrice': '90001'}}
            return {}
        no_thread = lambda **kwargs: SimpleNamespace(start=lambda: None, join=lambda: None)
        report = {}
        with patch.dict(control.__wrapped__.__globals__, api=api, Thread=no_thread,
                        stop_trial_robot_after_bootstrap=lambda *args: {'stopped': True}), \
                patch.dict(CAPACITY['CANCEL']['PRODUCT'], signed_login=lambda *args: {'token': 'fixture-broker'},
                           call=lambda *args: {'code': 0}):
            with control('fixture', report, products=wanted) as (location, products):
                self.assertEqual(('TEST01', wanted), (location, products))
        created = [row[2]['security_id'] for row in calls if row[1] == 'tenantProductDataSource']
        checked = [row[2]['securityID'] for row in calls if row[1] == 'queryPublicMarket']
        self.assertEqual(['BTC004USDT', 'BTC005USDT'], created)
        self.assertEqual(created, checked)
        self.assertTrue(report['price_source']['broker_key_deleted'])


if __name__ == '__main__':
    unittest.main()
