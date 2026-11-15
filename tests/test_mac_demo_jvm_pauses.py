from pathlib import Path
import runpy
import unittest

MOD = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/observe-mac-demo-jvm-pauses.py'))


class JvmPauseObservationTest(unittest.TestCase):
    def test_concurrent_complete_headers_require_identical_printed_uptime(self):
        stamp = '2026-11-16T07:56:20.917+0800: '
        body = ('Total time for which application threads were stopped: 0.0022636 seconds, '
                'Stopping threads took: 0.0000700 seconds')
        for prefix in [stamp + stamp + '971.774: 971.774: ',
                       stamp + '971.774: ' + stamp + '971.774: ']:
            event = MOD['parse_pause'](prefix + body)
            self.assertEqual('2026-11-15T23:56:20.917000+00:00', event['at'])
            self.assertEqual(2.2636, event['stopped_ms'])
            with self.assertRaises(ValueError):
                MOD['parse_pause'](prefix.replace('971.774:', '971.775:', 1) + body)

    def test_actual_date_inserted_after_complete_uptime_preserves_both_times(self):
        line = ('2026-11-16T07:54:54.687+0800: 885.544: 2026-11-16T07:54:54.687+0800: '
                'Total time for which application threads were stopped: 0.0027115 seconds, '
                'Stopping threads took: 0.0000528 seconds')
        event = MOD['parse_pause'](line)
        self.assertEqual('2026-11-15T23:54:54.687000+00:00', event['at'])
        self.assertEqual(event['at'], event['interleaved_extra_timestamp'])
        self.assertEqual(2.7115, event['stopped_ms'])
        with self.assertRaises(ValueError):
            MOD['parse_pause'](line + ' invalid trailing text')

    def test_actual_double_date_prefix_keeps_the_inner_uptime_anchor(self):
        lines = [
            '2026-11-16T07:52:43.390+0800: 2026-11-16T07:52:43.390+0800: '
            '754.247: [GC concurrent-root-region-scan-start]\n',
            '754.247: Total time for which application threads were stopped: '
            '0.0040025 seconds, Stopping threads took: 0.0001720 seconds\n']
        event, = MOD['parse_log_pauses'](lines, 'gc.log')
        self.assertEqual('2026-11-15T23:52:43.390000+00:00', event['at'])
        self.assertEqual(event['at'], event['interleaved_outer_timestamp'])
        self.assertEqual(4.0025, event['stopped_ms'])

    def test_actual_split_prefix_requires_adjacent_identical_uptime_and_retains_provenance(self):
        lines = [
            '2026-11-16T06:59:32.473+0800: 145.167: '
            '2026-11-16T06:59:32.473+0800: [GC concurrent-root-region-scan-start]\n',
            '145.167: Total time for which application threads were stopped: '
            '0.0042466 seconds, Stopping threads took: 0.0000555 seconds\n']
        events = MOD['parse_log_pauses'](iter(lines), 'gc.log')
        self.assertEqual(1, len(events))
        self.assertEqual('2026-11-15T22:59:32.473000+00:00', events[0]['at'])
        self.assertEqual(4.2466, events[0]['stopped_ms'])
        self.assertEqual((1, 2, 'gc.log'), (events[0]['interleaved_timestamp_prefix_line'],
                                         events[0]['line'], events[0]['file']))
        for changed in [[lines[1]], [lines[0], 'unrelated\n', lines[1]],
                        [lines[0].replace('145.167:', '145.166:'), lines[1]],
                        [lines[0], lines[1].rstrip() + ' invalid trailing text']]:
            with self.subTest(lines=changed), self.assertRaises(ValueError):
                MOD['parse_log_pauses'](changed, 'gc.log')

    def test_actual_interleaved_timestamp_preserves_complete_inner_pause_and_outer_time(self):
        line = ('2026-11-16T02:46:16.112+0800: 2026-11-16T02:46:16.111+0800: 21.582: '
                'Total time for which application threads were stopped: 0.0030066 seconds, '
                'Stopping threads took: 0.0000825 seconds')
        event = MOD['parse_pause'](line)
        self.assertEqual('2026-11-15T18:46:16.111000+00:00', event['at'])
        self.assertEqual('2026-11-15T18:46:16.112000+00:00', event['interleaved_outer_timestamp'])
        self.assertEqual(3.0066, event['stopped_ms'])
        with self.assertRaises(ValueError):
            MOD['parse_pause']('unrecognized prefix: ' + line)

    def test_actual_java8_record_preserves_timezone_and_millisecond_scale(self):
        event = MOD['parse_pause']('2026-11-15T10:36:55.184+0800: 0.283: '
                                  'Total time for which application threads were stopped: '
                                  '0.0107971 seconds, Stopping threads took: 0.0000124 seconds\n')
        self.assertEqual('2026-11-15T02:36:55.184000+00:00', event['at'])
        self.assertEqual(10.7971, event['stopped_ms'])
        self.assertEqual(.0124, event['stopping_threads_ms'])

    def test_window_counts_logged_events_without_mislabeling_request_latency(self):
        events = [{'at': '2026-11-15T10:00:00+0800', 'stopped_ms': 5000},
                  {'at': '2026-11-15T10:01:00+0800', 'stopped_ms': 10}]
        result = MOD['summarize'](events, MOD['at']('2026-11-15T02:00:00Z'),
                                  MOD['at']('2026-11-15T02:01:00Z'))
        self.assertEqual(1, result['events_logged_in_window'])
        self.assertEqual(5000, result['max_logged_stop_ms'])
        self.assertEqual(1, len(result['logged_stops_over_3000ms']))

    def test_missing_timestamps_and_truncated_pause_records_cannot_imply_no_pauses(self):
        self.assertIsNone(MOD['parse_pause']('Ordinary GC heap information\n'))
        with self.assertRaises(ValueError):
            MOD['parse_pause']('Total time for which application threads were stopped: 5 seconds')
        with self.assertRaises(ValueError):
            MOD['at']('2026-11-15T02:00:00')
