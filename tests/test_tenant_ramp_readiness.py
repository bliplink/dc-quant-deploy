"""Offline acceptance for fail-closed, read-only multitenant load-ramp gate."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("check-tenant-ramp-readiness.py")
spec = importlib.util.spec_from_file_location("ramp_guard", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class MultitenantRampGuardTests(unittest.TestCase):
    def sample(self, busy=0):
        return [
            {"location": f"A{index:05}", "events5m": 0 if index < busy else 3,
             "idleSeconds": 450 if index < busy else 12}
            for index in range(13)
        ]

    def test_current_pressure_and_silent_tenants_block_ramp(self):
        result = gate.evaluate(self.sample(busy=10), 59.68, 83.8, 77.0,
                               order_gc={"fullGCsIn3Seconds": 3,
                                         "oldGenerationMaxPercent": 99.99})
        self.assertEqual(result["gate"], "NOT_READY")
        self.assertEqual(result["tenantLocations"], 13)
        self.assertEqual(len(result["inactiveTenants"]), 10)
        self.assertTrue(any(x.startswith("MARKET_TRADES_INACTIVE") for x in result["reasons"]))
        self.assertTrue(any(x.startswith("CPU_PSI_HIGH") for x in result["reasons"]))
        self.assertTrue(any(x.startswith("ORDER_B_MEMORY_HIGH") for x in result["reasons"]))
        self.assertFalse(result["nextRampAuthorized"])
        self.assertTrue(any(x.startswith("ORDER_B_FULL_GC:") for x in result["reasons"]))
        self.assertTrue(any(x.startswith("ORDER_B_OLD_GEN_MAX_HIGH:") for x in result["reasons"]))

    def test_healthy_baseline_is_still_not_200_tenant_authorization(self):
        result = gate.evaluate(self.sample(busy=0), 1.2, 42, 20,
                               order_gc={"fullGCsIn3Seconds": 0,
                                         "oldGenerationMaxPercent": 40.0})
        self.assertEqual(result["gate"], "BASELINE_READY_ONLY")
        self.assertFalse(result["nextRampAuthorized"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["marketRowsLast300Seconds"], 39)
        self.assertAlmostEqual(result["marketRowsPerSecondNotOrderTPS"], 0.13)

    def test_cpu_threshold_normalizes_docker_percent_by_live_quota(self):
        gc = {"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 40}
        ok = gate.evaluate(self.sample(), 1, 10, 100, order_gc=gc,
                           robot_cpu_quota_cores=1.25)
        self.assertEqual("BASELINE_READY_ONLY", ok["gate"])
        self.assertEqual(80.0, ok["robotCpuQuotaUtilizationPercent"])
        saturated = gate.evaluate(self.sample(), 1, 10, 125, order_gc=gc,
                                  robot_cpu_quota_cores=1.25)
        self.assertEqual("NOT_READY", saturated["gate"])
        self.assertTrue(any("ROBOT_CPU_QUOTA_UTIL_HIGH:" in x
                            for x in saturated["reasons"]))

    def test_committed_full_but_max_has_headroom(self):
        gc = {"fullGCsIn3Seconds": 0,
              "oldGenerationCommittedPercent": 96.0,
              "oldGenerationMaxPercent": 6.4}
        result = gate.evaluate(self.sample(), 1, 10, 20, order_gc=gc)
        self.assertEqual("BASELINE_READY_ONLY", result["gate"])

    def test_memory_normalization(self):
        self.assertEqual(gate.memory_percent("1GiB / 2GiB"), 50)
        self.assertEqual(gate.memory_percent("512MiB / 1GiB"), 50)
        with self.assertRaises(ValueError):
            gate.memory_percent("not available")
        with self.assertRaises(ValueError):
            gate.memory_percent("12MiB / 0B")

    def test_fail_closed_on_invalid_clickhouse_data(self):
        for sample in ("", "A00001\tNaN\t0", "A00001\t1",
                       "A00001\t1\t0\nA00001\t3\t5", "A\t1\t0"):
            with self.assertRaises(ValueError):
                gate.market_rows(sample)

    def test_read_only_surface_and_zero_write_paths(self):
        content = SCRIPT.read_text()
        self.assertIn('READ_ONLY_METHODS = (', content)
        for unsafe in ('"placeOrder"', '"registerTenant"', '"stop"', '"kill"',
                       '"restart"', '"up"', '"create"', '"update"', '"execOrder"'):
            self.assertNotIn(unsafe, content)
        self.assertIn("countIf(createTime", content)
        self.assertNotIn("MYSQL_PASSWORD", content)
        self.assertNotIn("tapeApiSecret", content)

    def test_abnormal_resources_always_block(self):
        healthy_gc = {"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 20.0}
        for psi, mem, cpu in ((26, 10, 2), (2, 81, 2), (2, 10, 86)):
            self.assertEqual(gate.evaluate(
                self.sample(), psi, mem, cpu, order_gc=healthy_gc)["gate"], "NOT_READY")
        for gc in (None, {}, {"fullGCsIn3Seconds": -1, "oldGenerationMaxPercent": 40},
                   {"fullGCsIn3Seconds": 1, "oldGenerationMaxPercent": 40},
                   {"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 98}):
            self.assertEqual(gate.evaluate(self.sample(), 1, 10, 20, order_gc=gc)["gate"],
                             "NOT_READY")
        with self.assertRaises(ValueError):
            gate.evaluate(self.sample(), float("nan"), 10, 10)


if __name__ == "__main__":
    unittest.main()
