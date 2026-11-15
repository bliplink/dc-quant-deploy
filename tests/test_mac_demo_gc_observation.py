from pathlib import Path
import runpy
import unittest

FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))
OBSERVE = FRESH['gc_observation_environment']


class GcObservationTest(unittest.TestCase):
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
