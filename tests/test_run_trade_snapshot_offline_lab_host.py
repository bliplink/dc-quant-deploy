import argparse
import tempfile
import json
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.run_trade_snapshot_offline_lab_host import validate, execute, helper_fingerprint


class OfflineLabSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        java = root / "classes/com/app/dc/service/cluster/TradeSnapshotOfflineLab.class"
        java.parent.mkdir(parents=True)
        java.write_bytes(b"synthetic compiled class marker")
        self.args = argparse.Namespace(image="sha256:" + "a" * 64,
            journal_copy_root="/data/dc-saas-isolated-labs/trade-snapshot-test/journal",
            test_classes=str(root / "classes"), partition="P204", resident=None,
            heap_mib=768, memory_mib=1536, timeout_seconds=180, delta_batches=1000,
            output=str(root / "evidence.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_only_pinned_bounded_offline_inputs(self):
        validate(self.args)
        self.args.image = "local/tradesvr:latest"
        with self.assertRaises(ValueError): validate(self.args)

    def test_never_accepts_live_or_relative_journal_paths(self):
        for path in ["/data/dc-saas-runtime/data/TradeSvrA/journal",
                     "journal", "/data/dc-saas-isolated-labs/../dc-saas-runtime/journal"]:
            self.args.journal_copy_root = path
            with self.assertRaises(ValueError): validate(self.args)

    def test_rejects_unbounded_memory_time_and_delta(self):
        for field, value in [("heap_mib", 4096), ("memory_mib", 0),
                             ("timeout_seconds", 0), ("delta_batches", 1000000)]:
            previous = getattr(self.args, field)
            setattr(self.args, field, value)
            with self.assertRaises(ValueError): validate(self.args)
            setattr(self.args, field, previous)

    def test_preserves_existing_evidence(self):
        target = Path(self.args.output)
        target.write_text("existing evidence")
        with self.assertRaises(ValueError): validate(self.args)
        self.assertEqual("existing evidence", target.read_text())

    def test_capture_trials_are_bounded_and_require_explicit_resident(self):
        for value in (0, 6):
            self.args.capture_trials = value
            with self.assertRaises(ValueError): validate(self.args)
        self.args.capture_trials = 5
        with self.assertRaises(ValueError): validate(self.args)
        self.args.resident = "P122"
        validate(self.args)

    def test_helper_fingerprint_includes_nested_classes_and_rejects_escape(self):
        first = helper_fingerprint(self.args.test_classes)
        nested = Path(self.args.test_classes) / "com/app/dc/service/cluster/TradeSnapshotOfflineLab$Context.class"
        nested.write_bytes(b"synthetic nested class")
        second = helper_fingerprint(self.args.test_classes)
        self.assertNotEqual(first, second)
        self.assertEqual(second, helper_fingerprint(self.args.test_classes))
        nested.unlink()
        external = Path(self.tmp.name) / "outside.class"
        external.write_bytes(b"synthetic outside class")
        nested.symlink_to(external)
        with self.assertRaises(ValueError): helper_fingerprint(self.args.test_classes)

    def test_canonical_escape_fails_before_creating_container(self):
        with patch("tests.run_trade_snapshot_offline_lab_host.run") as command:
            command.return_value.stdout = "/data/dc-saas-runtime/data/TradeSvrA/journal\n"
            with self.assertRaises(ValueError): execute(self.args)
            self.assertEqual(1, command.call_count)

    def test_rejects_partitions_outside_current_256_partition_lab(self):
        self.args.partition = "P256"
        with self.assertRaises(ValueError): validate(self.args)
        self.args.partition = "P204"
        self.args.resident = "P999"
        with self.assertRaises(ValueError): validate(self.args)

    def test_history_audit_rejects_resident_or_unknown_modes(self):
        self.args.mode = "order-history-audit"
        validate(self.args)
        self.args.resident = "P122"
        with self.assertRaises(ValueError): validate(self.args)
        self.args.resident = None
        self.args.mode = "repair"
        with self.assertRaises(ValueError): validate(self.args)

    def test_unmarked_copy_fails_before_any_docker_operation(self):
        with patch("tests.run_trade_snapshot_offline_lab_host.run") as command:
            command.side_effect = [SimpleNamespace(stdout=self.args.journal_copy_root), RuntimeError("missing marker")]
            with self.assertRaises(RuntimeError): execute(self.args)
            self.assertEqual(2, command.call_count)
            self.assertTrue(all(call.args[0][0] == "colima" for call in command.call_args_list))

    def test_timeout_stops_only_fresh_lab_and_records_timeout_not_oom(self):
        state_reads = 0
        commands = []
        def fake_run(command, **kwargs):
            nonlocal state_reads
            commands.append(command)
            value = ""
            code = 0
            if command[0] == "colima" and "readlink" in command:
                value = command[-1]
            elif command[:2] == ["docker", "run"]:
                value = "/labs/trade-snapshot-run.TEST1234"
            elif command[:2] == ["docker", "inspect"]:
                state_reads += 1
                value = json.dumps({"Running": state_reads == 1, "ExitCode": 143, "OOMKilled": False})
            elif command[:2] == ["docker", "cp"]:
                code = 1
            return SimpleNamespace(stdout=value, returncode=code)
        with patch("tests.run_trade_snapshot_offline_lab_host.run", side_effect=fake_run), \
             patch("tests.run_trade_snapshot_offline_lab_host.time.monotonic", side_effect=[0, 200, 201]):
            self.assertEqual(1, execute(self.args))
        evidence = json.loads(Path(self.args.output).read_text())
        self.assertEqual("TIMEOUT", evidence["outcome"])
        self.assertFalse(evidence["cgroupOomKilled"])
        created = next(command for command in commands if command[:2] == ["docker", "create"])
        name = created[created.index("--name") + 1]
        self.assertTrue(name.startswith("dc-trade-offline-lab-"))
        cleanup = [command for command in commands if command[:2] in (["docker", "stop"], ["docker", "rm"])]
        self.assertEqual(2, len(cleanup))
        self.assertTrue(all(command[-1] == name for command in cleanup))


if __name__ == "__main__":
    unittest.main()
