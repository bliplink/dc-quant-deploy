from pathlib import Path
import runpy
import unittest


CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1]
                              / 'scripts/verify-mac-demo-execution-capacity.py'))


class ExecutionCapacityTest(unittest.TestCase):
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
