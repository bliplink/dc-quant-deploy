#!/usr/bin/env python3
"""Unit tests for the read-only deployed-Common auto failover audit."""
import importlib.util
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "t373_audit", HERE / "audit-t373-common-auto-failover-startup.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

BOOTSTRAP = """
public final class com.app.common.replication.CommonCertifiedNodeBootstrap {
  public static void openAndStartWithZkFencingAndReplay();
    Code:
       0: invokevirtual #66 // Method com/app/common/replication/CommonCertifiedNodeRuntime.startWithBusinessReplay:()V
}
"""
RUNTIME = """
public final class com.app.common.replication.CommonCertifiedNodeRuntime {
  public synchronized void start();
    Code:
       0: invokevirtual #66 // Method requireAuthenticatedReady:()V
  public synchronized void startWithBusinessReplay(java.lang.Object);
    Code:
       0: invokevirtual #66 // Method requireAuthenticatedReady:()V
}
"""

class TestT373(unittest.TestCase):
    def test_deployed_no_watch_is_no_go(self):
        report = audit.check_startup_disassembly(BOOTSTRAP, RUNTIME)
        self.assertEqual(report["bootstrap_entry_methods"], 1)
        self.assertEqual(report["node_start_methods"], 2)
        self.assertFalse(report["bootstrap_arms_watch"])
        self.assertFalse(report["node_start_arms_watch"])

    def test_actual_bootstrap_call_detected(self):
        altered = BOOTSTRAP.replace(
            "    Code:", "    Code:\n       1: invokevirtual #82 // Method "
            "com/app/common/replication/CommonCertifiedNodeRuntime.armAutomaticPhysicalRecoveryWatch:()V")
        self.assertTrue(audit.check_startup_disassembly(altered, RUNTIME)["bootstrap_arms_watch"])

    def test_only_method_declaration_never_counts(self):
        altered = RUNTIME.replace(
            "  public synchronized void start();",
            "  public synchronized void armAutomaticFailoverWatch(java.lang.String);\n"
            "    Code:\n       0: return\n"
            "  public synchronized void start();")
        self.assertFalse(audit.check_startup_disassembly(BOOTSTRAP, altered)["node_start_arms_watch"])

    def test_partition_watcher_thread_per_instance_detected(self):
        watch = """
public final class com.app.common.replication.CommonCertifiedFailoverWatch {
  public com.app.common.replication.CommonCertifiedFailoverWatch(java.lang.String);
    Code:
       0: invokestatic #30 // Method java/util/concurrent/Executors.newSingleThreadScheduledExecutor:()V
}
"""
        self.assertTrue(audit.per_instance_scheduled_thread(watch))

    def test_shared_scheduler_does_not_trigger_per_watch_gate(self):
        watch = """
public final class com.app.common.replication.CommonCertifiedFailoverWatch {
  public com.app.common.replication.CommonCertifiedFailoverWatch(java.lang.String);
    Code:
       0: getstatic #30 // Field nodeSharedScheduler:Ljava/util/concurrent/ScheduledExecutorService;
}
"""
        self.assertFalse(audit.per_instance_scheduled_thread(watch))

    def test_source_comment_never_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "NoWiring.java").write_text(
                "// node.armAutomaticFailoverWatch();\n"
                "/* runtime.armAutomaticPhysicalRecoveryWatch(); */\n"
                "class NoWiring {}\n", encoding="utf-8")
            report = audit.inspect_source_dirs({"Order": root})
            self.assertFalse(report["Order"]["wiring_arms_watch"])
            (root / "RealWiring.java").write_text(
                "class RealWiring { void start() { node.armAutomaticPhysicalRecoveryWatch(); } }\n",
                encoding="utf-8")
            report = audit.inspect_source_dirs({"Order": root})
            self.assertTrue(report["Order"]["wiring_arms_watch"])

if __name__ == "__main__":
    unittest.main()
