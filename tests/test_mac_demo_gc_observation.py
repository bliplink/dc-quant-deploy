from pathlib import Path
import runpy
import unittest

FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))
OBSERVE = FRESH['gc_observation_environment']
LOW_PAUSE = FRESH['low_pause_gc_environment']


class GcObservationTest(unittest.TestCase):
    def test_new_core_gc_tuning_preserves_ack_heap_and_bounded_observation(self):
        original = ['JAVA_OPTS=-Xms128m -Xmx2g',
                    'JAVA_TOOL_OPTIONS=-Dcommon.certified.clientAckPolicy=LOCAL_DURABLE_ASYNC']
        observed = OBSERVE(original)
        values = dict(x.split('=', 1) for x in LOW_PAUSE(observed))
        self.assertEqual('-Xms128m -Xmx2g', values['JAVA_OPTS'])
        self.assertEqual(original[1].split('=', 1)[1], values['JAVA_TOOL_OPTIONS'])
        self.assertIn('-Xloggc:/srv/dc/log/jvm-gc.log', values['EXTRA_JAVA_OPTS'])
        self.assertIn('-XX:+UseG1GC -XX:MaxGCPauseMillis=10', values['EXTRA_JAVA_OPTS'])
        self.assertEqual(LOW_PAUSE(observed), LOW_PAUSE(LOW_PAUSE(observed)))

    def test_operator_gc_choice_or_pause_budget_is_never_overwritten(self):
        for key in ('JAVA_OPTS', 'EXTRA_JAVA_OPTS', 'JAVA_TOOL_OPTIONS'):
            for collector in ('G1', 'Parallel', 'Serial', 'ConcMarkSweep'):
                entries = [key + '=-XX:+Use' + collector + 'GC -XX:MaxGCPauseMillis=25']
                with self.subTest(key=key, collector=collector):
                    self.assertEqual(entries, LOW_PAUSE(entries))
        self.assertEqual(['JAVA_OPTS=-XX:-UseG1GC'], LOW_PAUSE(['JAVA_OPTS=-XX:-UseG1GC']))
        values = dict(x.split('=', 1) for x in LOW_PAUSE(['JAVA_OPTS=-XX:MaxGCPauseMillis=25']))
        self.assertEqual('-XX:+UseG1GC', values['EXTRA_JAVA_OPTS'])

    def test_service_pause_logs_do_not_change_ack_heap_or_diagnostic_children(self):
        original = ['JAVA_OPTS=-Xmx2g -XX:MaxDirectMemorySize=512m',
                    'JAVA_TOOL_OPTIONS=-Dcommon.certified.clientAckPolicy=STRICT_QUORUM',
                    'EXTRA_JAVA_OPTS=-ea', 'MAIN_CLASS=TradeSvr']
        values = dict(x.split('=', 1) for x in OBSERVE(original))
        self.assertEqual(original[0].split('=', 1)[1], values['JAVA_OPTS'])
        self.assertEqual(original[1].split('=', 1)[1], values['JAVA_TOOL_OPTIONS'])
        self.assertEqual('TradeSvr', values['MAIN_CLASS'])
        self.assertTrue(values['EXTRA_JAVA_OPTS'].startswith('-ea '))
        self.assertIn('-XX:+PrintGCApplicationStoppedTime', values['EXTRA_JAVA_OPTS'])
        self.assertIn('-Xloggc:/srv/dc/log/jvm-gc.log', values['EXTRA_JAVA_OPTS'])
        self.assertIn('-XX:NumberOfGCLogFiles=5', values['EXTRA_JAVA_OPTS'])
        self.assertIn('-XX:GCLogFileSize=10M', values['EXTRA_JAVA_OPTS'])
        self.assertNotIn('UseG1GC', values['EXTRA_JAVA_OPTS'])
        self.assertEqual(OBSERVE(original), OBSERVE(OBSERVE(original)))

    def test_explicit_observers_remain_untouched_in_every_option_source(self):
        for key in ['JAVA_OPTS', 'EXTRA_JAVA_OPTS', 'JAVA_TOOL_OPTIONS']:
            for custom in ['-Xloggc:/custom/gc.log', '-XX:+PrintGCDetails',
                           '-XX:-PrintGCApplicationStoppedTime', '-XX:GCLogFileSize=2M']:
                entries = [key + '=' + custom]
                with self.subTest(key=key, custom=custom):
                    self.assertEqual(entries, OBSERVE(entries))
