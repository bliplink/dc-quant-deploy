from pathlib import Path
import os
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

DRIVER = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                              'scripts/verify-mac-demo-distributed-execution-capacity.py'))


class DistributedReceiptTest(unittest.TestCase):
    def test_owner_thousand_target_uses_sufficient_normal_sessions(self):
        budget = DRIVER['validate_offered_load'](16, 65, 60)
        self.assertEqual(1040, budget['total_offered_executions_per_second'])
        self.assertFalse(budget['gateway_profile_changed'])
        # This previously permitted plan exceeds the real per-session quota.
        # Reject it before tenant creation, funding, or any pressure is sent.
        for rate in (130, float('inf'), float('nan'), 0):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                DRIVER['validate_offered_load'](8, rate, 60)

    def streams(self):
        streams = []
        for i, side in enumerate('AB'):
            streams.append({'location': 'TENANT' + side, 'order_partition': 'P%03d' % (i * 128),
                            'trade_partition': 'P%03d' % (i * 128 + 1),
                            'order_primary': 'OrderSvr' + side, 'trade_primary': 'TradeSvr' + side,
                            'measurement': {'from': '2026-11-14T08:00:00+00:00',
                                'actual_start': '2026-11-14T08:00:00.001+00:00',
                                'planned_orders': 1, 'scheduler_drops': 0,
                                'fills_inside_offered_window': 1, 'stream_errors': [],
                                'measurement_complete': True, 'orders': [{
                                    'client_order_id': 'client-' + side, 'execution_id': 'exec-' + side,
                                    'outcome': 'ACKNOWLEDGED', 'client_fill_ms': 10 + i,
                                    'settlement_durability': 'QUORUM_DURABLE', 'settlement_rpo_risk': False,
                                    'scheduled_fill_ms': 11 + i, 'ack_ms': 2 + i, 'dispatch_delay_ms': 1}]}})
        return streams

    def test_independent_partition_final_receipts_form_one_combined_distribution(self):
        result = DRIVER['summarize_streams'](self.streams(), 60)
        self.assertTrue(result['window_capacity_pass'])
        self.assertEqual(2, result['client_fill_ms']['samples'])
        self.assertEqual(11, result['client_fill_ms']['p99'])

    def test_tail_completion_cannot_be_reported_as_window_capacity(self):
        streams = self.streams()
        streams[1]['measurement']['fills_inside_offered_window'] = 0
        result = DRIVER['summarize_streams'](streams, 60)
        self.assertTrue(result['all_accepted_final_receipts_pass'])
        self.assertFalse(result['window_capacity_pass'])

        self.assertEqual(.5, result['window_delivery_fraction'])

    def test_rpc_ack_without_final_trade_cannot_satisfy_capacity(self):
        streams = self.streams()
        del streams[1]['measurement']['orders'][0]['execution_id']
        result = DRIVER['summarize_streams'](streams, 60)
        self.assertFalse(result['all_accepted_final_receipts_pass'])
        self.assertEqual(1, result['missing_final_receipts'])

    def test_ioc_cancellation_is_visible_and_never_becomes_a_final_fill(self):
        stream = {'run': 'fixture', 'location': 'TEST01', 'symbol': 'BTC005USDT',
                  'measurement': {'orders': [{'client_order_id': 'cancelled-order'}]}}
        with patch.dict(DRIVER['CANCEL']['PRODUCT'], readonly_sql=lambda sql:
                        [['cancelled-order', 'Cancelled', '0', '0', 'BTC005USDT', '4']]):
            result = DRIVER['projected_stream'](stream)
        self.assertFalse(result['consistent'])
        self.assertEqual({'Cancelled': 1}, result['order_status_counts'])
        self.assertEqual({'0': 1}, result['execution_count_distribution'])
        self.assertEqual(['cancelled-order'], result['nonfilled_client_order_ids'])

    def test_a_mode_label_cannot_replace_the_actual_receipt_durability(self):
        streams = self.streams()
        self.assertTrue(DRIVER['summarize_streams'](streams, 60, 'STRICT_QUORUM')['window_capacity_pass'])
        wrong = DRIVER['summarize_streams'](streams, 60, 'LOCAL_DURABLE_ASYNC')
        self.assertIn('SETTLEMENT_DURABILITY_POLICY_MISMATCH', wrong['stream_errors'])
        self.assertFalse(wrong['window_capacity_pass'])

    def test_duplicate_execution_across_connections_is_a_protocol_error(self):
        streams = self.streams()
        streams[1]['measurement']['orders'][0]['execution_id'] = 'exec-A'
        result = DRIVER['summarize_streams'](streams, 60)
        self.assertIn('DUPLICATE_FINAL_EXECUTION_ACROSS_STREAMS', result['stream_errors'])
        self.assertFalse(result['all_accepted_final_receipts_pass'])

    def test_accounted_unsent_slot_is_capacity_failure_while_sent_orders_finish(self):
        streams = self.streams()
        streams[0]['measurement'].update(planned_orders=2, scheduler_drops=1)
        result = DRIVER['summarize_streams'](streams, 60)
        self.assertEqual((3, 2, 1), (result['planned_orders'], result['sent_orders'], result['scheduler_drops']))
        self.assertTrue(result['generator_accounting_pass'])
        self.assertTrue(result['all_accepted_final_receipts_pass'])
        self.assertFalse(result['window_capacity_pass'])

    def test_unsent_slot_cannot_hide_a_missing_final_execution_or_missing_accounting(self):
        streams = self.streams()
        streams[0]['measurement'].update(planned_orders=2, scheduler_drops=1)
        del streams[1]['measurement']['orders'][0]['execution_id']
        self.assertFalse(DRIVER['summarize_streams'](streams, 60)['all_accepted_final_receipts_pass'])
        streams = self.streams()
        streams[0]['measurement']['planned_orders'] = 2
        result = DRIVER['summarize_streams'](streams, 60)
        self.assertFalse(result['generator_accounting_pass'])
        self.assertFalse(result['all_accepted_final_receipts_pass'])

    def test_shared_or_unbalanced_partitions_are_not_a_distributed_measurement(self):
        for key in ['order_partition', 'trade_partition', 'order_primary', 'trade_primary']:
            streams = self.streams()
            streams[1][key] = streams[0][key]
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                DRIVER['summarize_streams'](streams, 60)

    def test_a_common_scheduled_time_cannot_hide_late_actual_start(self):
        streams = self.streams()
        streams[1]['measurement']['actual_start'] = '2026-11-14T08:00:00.301+00:00'
        result = DRIVER['summarize_streams'](streams, 60)
        self.assertEqual(300, result['start_spread_ms'])
        self.assertFalse(result['window_capacity_pass'])

    def test_many_sessions_on_one_book_are_one_matching_queue(self):
        streams = self.streams()
        streams[1].update(location=streams[0]['location'], symbol='BTC004USDT',
                          order_partition=streams[0]['order_partition'], trade_partition=streams[0]['trade_partition'],
                          order_primary=streams[0]['order_primary'], trade_primary=streams[0]['trade_primary'])
        layout = DRIVER['matching_layout'](2, tenants=1, symbols_per_tenant=1)
        result = DRIVER['summarize_streams'](streams, 60, 'STRICT_QUORUM', layout)
        self.assertEqual((1, 1, 2), (result['tenant_count'], result['matching_queue_count'],
                                   result['queues'][0]['native_sessions']))
        self.assertEqual(2, result['queues'][0]['measurement']['client_fill_ms']['samples'])
        self.assertTrue(result['window_capacity_pass'])

    def test_one_tenant_many_symbols_share_trade_partition_but_keep_queue_tails(self):
        streams = self.streams()
        streams[0]['symbol'] = 'BTC004USDT'
        streams[1].update(location=streams[0]['location'], symbol='BTC005USDT',
                          trade_partition=streams[0]['trade_partition'], trade_primary=streams[0]['trade_primary'])
        streams[1]['measurement']['orders'][0]['client_fill_ms'] = 900
        streams[1]['measurement']['fills_inside_offered_window'] = 0
        layout = DRIVER['matching_layout'](2, tenants=1, symbols_per_tenant=2)
        result = DRIVER['summarize_streams'](streams, 60, 'STRICT_QUORUM', layout)
        self.assertEqual((1, 2), (result['tenant_count'], result['matching_queue_count']))
        self.assertEqual({'P001': 2}, result['queues_by_trade_partition'])
        self.assertEqual([10, 900], [q['measurement']['client_fill_ms']['p99'] for q in result['queues']])
        self.assertFalse(result['window_capacity_pass'])

    def test_natural_partition_collision_is_visible_only_in_declared_matrix(self):
        streams = self.streams()
        streams[1].update(trade_partition=streams[0]['trade_partition'], trade_primary=streams[0]['trade_primary'])
        with self.assertRaises(RuntimeError):
            DRIVER['summarize_streams'](streams, 60)
        layout = DRIVER['matching_layout'](2, tenants=2, symbols_per_tenant=1)
        result = DRIVER['summarize_streams'](streams, 60, 'STRICT_QUORUM', layout)
        self.assertEqual({'P001': 2}, result['queues_by_trade_partition'])
        self.assertTrue(result['window_capacity_pass'])

    def test_mislabeled_matrix_and_non_divisible_plan_fail_before_acceptance(self):
        for tenants, symbols in [(0, 1), (1, 0), (3, 1), (1, 3), (2, 2)]:
            with self.subTest(tenants=tenants, symbols=symbols), self.assertRaises(ValueError):
                DRIVER['matching_layout'](2, tenants, symbols)
        layout = DRIVER['matching_layout'](2, tenants=1, symbols_per_tenant=1)
        with self.assertRaises(RuntimeError):
            DRIVER['summarize_streams'](self.streams(), 60, 'STRICT_QUORUM', layout)

    def test_projected_execution_must_belong_to_the_requested_real_product(self):
        stream = {'run': 'fixture', 'location': 'TEST01', 'symbol': 'BTC005USDT',
                  'measurement': {'orders': [{'client_order_id': 'order'}]}}
        for symbol, market, passed in [('BTC005USDT', '4', True), ('BTC004USDT', '4', False),
                                       ('BTC005USDT', '5', False)]:
            rows = [['order', 'Filled', '1', '0.001', symbol, market]]
            with self.subTest(symbol=symbol, market=market), \
                    patch.dict(DRIVER['CANCEL']['PRODUCT'], readonly_sql=lambda sql: rows):
                result = DRIVER['projected_stream'](stream)
                self.assertEqual(passed, result['consistent'])


class DistributedEntryTest(unittest.TestCase):
    def test_mac_entry_preserves_native_options_and_child_failure(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binpath = Path(directory)
            (binpath / 'uname').write_text('#!/bin/sh\necho Darwin\n')
            (binpath / 'python3').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 7\n')
            for file in binpath.iterdir():
                file.chmod(0o700)
            command = ['bash', str(root / 'mac-colima-saas.sh'), 'verify-distributed-execution',
                       '/demo', '--streams', '4', '--rate-per-stream', '5', '--seconds', '60']
            result = subprocess.run(command, capture_output=True, text=True,
                                    env=dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH']))
            self.assertEqual(7, result.returncode)
            self.assertEqual([str(root / 'scripts/verify-mac-demo-distributed-execution-capacity.py'),
                              *command[3:]], result.stdout.splitlines())


if __name__ == '__main__':
    unittest.main()
