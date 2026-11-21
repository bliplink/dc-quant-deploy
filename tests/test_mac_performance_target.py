from pathlib import Path
import runpy
import unittest


TARGET = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            'scripts/mac-demo-performance-target.py'))


class PerformanceAcceptanceTest(unittest.TestCase):
    def aggregate(self):
        return {'sent_orders': 60002, 'planned_orders': 60002, 'final_executions': 60002,
                'fills_inside_offered_window': 60000, 'observed_window_execution_rate': 1000,
                'all_accepted_final_receipts_pass': True, 'generator_accounting_pass': True,
                'scheduler_drops': 0, 'client_fill_ms': {'samples': 60002, 'p99': 20},
                'scheduled_fill_ms': {'samples': 60002, 'p99': 20}}

    def test_target_uses_actual_window_fills_and_keeps_tail_receipts_visible(self):
        result = TARGET['execution_target'](self.aggregate(), 60, True)
        self.assertTrue(result['passed'])
        self.assertEqual(2, result['tail_final_receipts_after_window'])
        slower = self.aggregate()
        slower['observed_window_execution_rate'] = 999
        self.assertFalse(TARGET['execution_target'](slower, 60, True)['passed'])

    def test_profiled_window_keeps_accounting_but_cannot_satisfy_performance(self):
        result = TARGET['execution_target'](self.aggregate(), 60, True, qualified_window=False)
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['qualified_window'])
        self.assertTrue(result['checks']['all_requests_and_fills_accounted'])
        self.assertEqual(1000, result['observed_per_second'])

    def test_missing_failed_dropped_or_unsampled_requests_cannot_pass(self):
        for key, value in (('all_accepted_final_receipts_pass', False),
                           ('generator_accounting_pass', False), ('scheduler_drops', 1),
                           ('final_executions', 60001),
                           ('client_fill_ms', {'samples': 60001, 'p99': 1}),
                           ('scheduled_fill_ms', {'samples': 60002, 'p99': 21})):
            with self.subTest(key=key):
                changed = self.aggregate()
                changed[key] = value
                self.assertFalse(TARGET['execution_target'](changed, 60, True)['passed'])

    def test_fast_rpc_ack_cannot_replace_the_final_trade_receipt(self):
        changed = self.aggregate()
        changed['ack_ms'] = {'samples': 60002, 'p99': 1}
        changed['client_fill_ms'] = {'samples': 60002, 'p99': 100}
        self.assertFalse(TARGET['execution_target'](changed, 60, True)['passed'])
        self.assertFalse(TARGET['execution_target'](self.aggregate(), 59, True)['passed'])
        self.assertFalse(TARGET['execution_target'](self.aggregate(), 60, False)['passed'])

    def test_cycles_are_two_commands_and_each_terminal_distribution_is_required(self):
        pair = {'passed': True, 'new_inside_window': True, 'cancel_inside_window': True}
        phase = {'passed': True, 'elapsed_seconds': 60.2, 'window_seconds': 60, 'records': [pair] * 30000,
                 'place_new_ms': {'samples': 30000, 'p99': 20},
                 'cancel_terminal_ms': {'samples': 30000, 'p99': 20}}
        result = TARGET['order_cancel_target'](phase, 'tcp')
        self.assertTrue(result['passed'])
        self.assertEqual(1000, result['observed_per_second'])
        self.assertFalse(TARGET['order_cancel_target'](phase, 'http')['passed'])
        busy = dict(phase, records=phase['records'] + [{'outcome': 'ORDER_BUSY_RETRYABLE', 'passed': False}])
        result = TARGET['order_cancel_target'](busy, 'tcp')
        self.assertFalse(result['passed'])
        self.assertEqual(1000, result['observed_per_second'])
        late = dict(phase, records=[*phase['records'][:-1], dict(pair, cancel_inside_window=False)])
        observed = TARGET['order_cancel_target'](late, 'tcp')
        self.assertFalse(observed['passed'])
        self.assertEqual((59999, 1), (observed['window_commands'], observed['late_commands']))
        for key, value in (('window_seconds', 61), ('passed', False), ('records', [{'passed': True}] * 30000),
                           ('cancel_terminal_ms', {'samples': 29999, 'p99': 1}),
                           ('place_new_ms', {'samples': 30000, 'p99': 21})):
            with self.subTest(key=key):
                changed = dict(phase, **{key: value})
                self.assertFalse(TARGET['order_cancel_target'](changed, 'tcp')['passed'])


if __name__ == '__main__':
    unittest.main()
