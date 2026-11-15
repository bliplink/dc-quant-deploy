from pathlib import Path
import runpy
import unittest

MOD = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/observe-mac-demo-jvm-pauses.py'))


class JvmPauseObservationTest(unittest.TestCase):
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
