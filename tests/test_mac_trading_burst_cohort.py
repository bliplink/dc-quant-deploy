from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


BURST = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-trading-burst.py'))


class TradingBurstCohortTest(unittest.TestCase):
    def test_selection_is_limited_to_the_measured_running_cohort(self):
        baseline = {'runtime_status': {'XYZ123': 'RUNNING', 'ABC456': 'RUNNING'}}
        with patch.dict(BURST['PRODUCT'], readonly_sql=lambda sql: self.query(sql)):
            self.assertEqual(['ABC456'], BURST['burst_tenants'](baseline, 0))

    def query(self, sql):
        self.assertIn("approved_location IN ('ABC456','XYZ123')", sql)
        self.assertIn('LIMIT 12 OFFSET 0', sql)
        return [['ABC456']]

    def test_historical_approved_tenant_outside_the_baseline_is_rejected(self):
        baseline = {'runtime_status': {'XYZ123': 'RUNNING'}}
        with patch.dict(BURST['PRODUCT'], readonly_sql=lambda sql: [['OLD789']]):
            with self.assertRaisesRegex(RuntimeError, 'No measured'):
                BURST['burst_tenants'](baseline, 0)

    def test_nonrunning_and_invalid_cohorts_fail_before_querying(self):
        for active in [{}, {'XYZ123': 'STOPPED'}, {"X' OR 1=1": 'RUNNING'}]:
            with self.subTest(active=active), patch.dict(BURST['PRODUCT'], readonly_sql=self.fail):
                with self.assertRaisesRegex(RuntimeError, 'measured running'):
                    BURST['burst_tenants']({'runtime_status': active}, 0)


if __name__ == '__main__':
    unittest.main()
