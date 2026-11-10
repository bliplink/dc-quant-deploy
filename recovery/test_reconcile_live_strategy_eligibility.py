import unittest

from recovery.reconcile_live_strategy_eligibility import build_rows, confirmed_failure, offline_request


class EligibilityReconciliationTest(unittest.TestCase):
    def row(self, reason='oos_not_passed'):
        return {'strategy_name': 'sample', 'strategy_version': 'v1',
                'symbol_scope': 'ETHUSDT', 'text_scope': '15m', 'reason': reason}

    def test_request_is_exact_status_only_and_rechecked_on_server(self):
        request = offline_request(self.row())
        self.assertIs(request['closePositions'], False)
        self.assertIs(request['requireIneligible'], True)
        self.assertEqual(request['strategyVersion'], 'v1')
        self.assertIn('oos_not_passed', request['reason'])

    def test_qualified_and_missing_evidence_are_not_retirement_targets(self):
        for reason in ('qualified', 'realistic_backtest_missing'):
            self.assertFalse(confirmed_failure(self.row(reason)))
            with self.assertRaises(ValueError):
                offline_request(self.row(reason))

    def test_broad_or_missing_scope_is_rejected(self):
        for field in ('strategy_name', 'strategy_version', 'symbol_scope', 'text_scope'):
            for value in ('', '*', 'ETHUSDT,SOLUSDT', 'ETHUSDT|SOLUSDT'):
                row = self.row()
                row[field] = value
                with self.assertRaises(ValueError):
                    offline_request(row)

    def test_snapshot_does_not_invent_missing_evidence(self):
        self.assertEqual(build_rows([self.row()], [])[0]['reason'], 'realistic_backtest_missing')


if __name__ == '__main__':
    unittest.main()
