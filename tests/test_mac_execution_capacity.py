import ast
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest


CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1]
                              / 'scripts/verify-mac-demo-execution-capacity.py'))


class ExecutionCapacityTest(unittest.TestCase):
    def test_offered_load_can_reach_fifteen_without_exceeding_nine_hundred_orders(self):
        source = Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-execution-capacity.py'
        tree = ast.parse(source.read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        guard = next(node for node in main.body if isinstance(node, ast.If))
        condition = compile(ast.Expression(guard.test), 'actual-client-capacity-admission', 'eval')
        for rate, seconds, rejected in [(1, 60, False), (10, 60, False), (15, 60, False),
                                        (3, 300, False), (15.01, 60, True), (15, 61, True),
                                        (0, 60, True), (15, 59, True)]:
            with self.subTest(rate=rate, seconds=seconds):
                self.assertEqual(rejected, eval(condition, {'args': SimpleNamespace(rate=rate, seconds=seconds)}))

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
