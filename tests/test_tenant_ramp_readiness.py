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

    def healthy(self):
        return [{"location": f"A{index:05}", "robotId": "maker",
                 "status": "RUNNING", "openOrders": 40,
                 "heartbeatAgeSeconds": 3} for index in range(13)]

    def test_enabled_robot_status_validation(self):
        payload = "\n".join(["A00001\tmaker\tRUNNING\t40\t2",
                              "DUJE16\tmaker\tDEGRADED\t0\t4"])
        robots = gate.parse_enabled_robot_rows(payload)
        self.assertEqual(len(robots), 2)
        self.assertEqual(robots[1]["location"], "DUJE16")
        for invalid in ("", "A00001\tmaker\tRUNNING", "x!\tbot\tRUNNING\t40\t2",
                        "A00001\tmaker\tRUNNING\t40\tabc",
                        "A00001\tmaker\tRUNNING\t40\t2\nA00001\tmaker\tRUNNING\t40\t2"):
            with self.assertRaises(ValueError):
                gate.parse_enabled_robot_rows(invalid)

    def test_enabled_degraded_robot_blocks_ramp(self):
        robots = self.healthy()
        robots[3] = dict(robots[3], location="DUJE16", status="DEGRADED",
                         openOrders=0, heartbeatAgeSeconds=3)
        outcome = gate.evaluate(self.sample(), 1.0, 10.0, 20.0,
            order_gc={"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 5.0},
            enabled_robots=robots, partition_signals=[])
        self.assertEqual(outcome["gate"], "NOT_READY")
        self.assertIn("ENABLED_ROBOTS_UNHEALTHY:1/13", outcome["reasons"])
        self.assertEqual(outcome["enabledRobotsUnhealthy"][0]["location"], "DUJE16")

    def test_current_pressure_and_silent_tenants_block_ramp(self):
        result = gate.evaluate(self.sample(busy=10), 59.68, 83.8, 77.0,
                               order_gc={"fullGCsIn3Seconds": 3,
                                         "oldGenerationMaxPercent": 99.99},
                                         enabled_robots=self.healthy(), partition_signals=[])
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
                                         "oldGenerationMaxPercent": 40.0},
                                         enabled_robots=self.healthy(), partition_signals=[])
        self.assertEqual(result["gate"], "BASELINE_READY_ONLY")
        self.assertFalse(result["nextRampAuthorized"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["marketRowsLast300Seconds"], 39)
        self.assertAlmostEqual(result["marketRowsPerSecondNotOrderTPS"], 0.13)

    def test_cpu_threshold_normalizes_docker_percent_by_live_quota(self):
        gc = {"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 40}
        ok = gate.evaluate(self.sample(), 1, 10, 100, order_gc=gc,
                           robot_cpu_quota_cores=1.25, enabled_robots=self.healthy(), partition_signals=[])
        self.assertEqual("BASELINE_READY_ONLY", ok["gate"])
        self.assertEqual(80.0, ok["robotCpuQuotaUtilizationPercent"])
        saturated = gate.evaluate(self.sample(), 1, 10, 125, order_gc=gc,
                                  robot_cpu_quota_cores=1.25, enabled_robots=self.healthy(), partition_signals=[])
        self.assertEqual("NOT_READY", saturated["gate"])
        self.assertTrue(any("ROBOT_CPU_QUOTA_UTIL_HIGH:" in x
                            for x in saturated["reasons"]))

    def test_committed_full_but_max_has_headroom(self):
        gc = {"fullGCsIn3Seconds": 0,
              "oldGenerationCommittedPercent": 96.0,
              "oldGenerationMaxPercent": 6.4}
        result = gate.evaluate(self.sample(), 1, 10, 20, order_gc=gc, enabled_robots=self.healthy(), partition_signals=[])
        self.assertEqual("BASELINE_READY_ONLY", result["gate"])

    def test_order_partition_recovery_errors_block_next_ramp(self):
        log = ("2026-10-10 WARN ORDER_PARTITION_PROMOTION_BARRIER_RETRY node:OrderSvrA, "
               "partition:P246, epoch:1\n"
               "2026-10-10 ERROR ORDER_PARTITION_RECOVERY_FAILED node:OrderSvrA, "
               "partition:P246, epoch:1\n"
               "2026-10-10 WARN partition fence rejected request, "
               "reason:PARTITION_NOT_READY service=OrderSvrA, partition=P246, epoch=1")
        signals = gate.parse_partition_recovery_signals(log, "dc-saas-ordersvr")
        self.assertEqual(1, len(signals))
        self.assertEqual(1, signals[0]["recoveryFailures"])
        self.assertEqual(1, signals[0]["notReadyRejections"])
        self.assertEqual("P246", signals[0]["partition"])
        healthy_gc = {"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 5.0}
        result = gate.evaluate(self.sample(), 1, 10, 20, order_gc=healthy_gc,
                               enabled_robots=self.healthy(), partition_signals=signals)
        self.assertEqual("NOT_READY", result["gate"])
        self.assertIn("ORDER_PARTITIONS_UNREADY:P246", result["reasons"])
        good = gate.evaluate(self.sample(), 1, 10, 20, order_gc=healthy_gc,
                             enabled_robots=self.healthy(), partition_signals=[])
        self.assertEqual("BASELINE_READY_ONLY", good["gate"])
        unknown = gate.evaluate(self.sample(), 1, 10, 20, order_gc=healthy_gc,
                                enabled_robots=self.healthy())
        self.assertIn("ORDER_PARTITION_RECOVERY_TELEMETRY_MISSING", unknown["reasons"])

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

    def test_fresh_empty_market_is_named_without_authorizing_ramp(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        output = io.StringIO()
        with patch.object(gate, "collect", side_effect=ValueError("empty market-trade baseline")), \
             patch("sys.argv", ["check-tenant-ramp-readiness.py"]), \
             contextlib.redirect_stdout(output):
            self.assertEqual(2, gate.main())
        result = json.loads(output.getvalue())
        self.assertEqual(result["gate"], "NOT_READY")
        self.assertFalse(result["nextRampAuthorized"])
        self.assertEqual(result["reasons"], ["MARKET_ACTIVITY_BASELINE_EMPTY"])

    def test_invalid_market_rows_still_fail_as_unavailable(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        output = io.StringIO()
        with patch.object(gate, "collect", side_effect=ValueError("duplicate tenant locations")), \
             patch("sys.argv", ["check-tenant-ramp-readiness.py"]), \
             contextlib.redirect_stdout(output):
            self.assertEqual(2, gate.main())
        self.assertEqual(json.loads(output.getvalue())["reasons"], ["TELEMETRY_UNAVAILABLE"])

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
                self.sample(), psi, mem, cpu, order_gc=healthy_gc, enabled_robots=self.healthy(), partition_signals=[])["gate"], "NOT_READY")
        for gc in (None, {}, {"fullGCsIn3Seconds": -1, "oldGenerationMaxPercent": 40},
                   {"fullGCsIn3Seconds": 1, "oldGenerationMaxPercent": 40},
                   {"fullGCsIn3Seconds": 0, "oldGenerationMaxPercent": 98}):
            self.assertEqual(gate.evaluate(self.sample(), 1, 10, 20, order_gc=gc, enabled_robots=self.healthy(), partition_signals=[])["gate"],
                             "NOT_READY")
        with self.assertRaises(ValueError):
            gate.evaluate(self.sample(), float("nan"), 10, 10)


if __name__ == "__main__":
    unittest.main()
