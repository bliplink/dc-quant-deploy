from pathlib import Path
import os
import runpy
import subprocess
import tempfile
import unittest

DRIVER = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                              'scripts/verify-mac-demo-distributed-execution-capacity.py'))


class DistributedReceiptTest(unittest.TestCase):
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
        self.assertFalse(DRIVER['summarize_streams'](streams, 60)['all_accepted_final_receipts_pass'])

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
