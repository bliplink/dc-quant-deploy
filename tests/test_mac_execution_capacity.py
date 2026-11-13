import ast
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1]
                              / 'scripts/verify-mac-demo-execution-capacity.py'))


class ExecutionCapacityTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
