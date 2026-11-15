import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("runtime_observer", Path(__file__).resolve().parents[1] / "scripts/verify-mac-demo-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
VALID = "node=OrderSvrA\nrole_ok=256\nwriter_ok=128\nexpected_writers=128\nopened_partitions=256\nreservations=0\n"


class RuntimeObservationTest(unittest.TestCase):
    def test_complete_physical_census(self):
        self.assertEqual(runtime.validate_observation(VALID, "OrderSvrA", 128)["writer_ok"], "128")

    def test_ready_manifest_cannot_hide_missing_physical_role_or_writer(self):
        for previous, missing in [("role_ok=256", "role_ok=255"), ("writer_ok=128", "writer_ok=127"),
                                  ("opened_partitions=256", "opened_partitions=255"), ("reservations=0", "reservations=1")]:
            with self.subTest(field=previous), self.assertRaises(ValueError):
                runtime.validate_observation(VALID.replace(previous, missing), "OrderSvrA", 128)

    def test_partial_duplicate_and_error_rows_rejected(self):
        for invalid in [VALID.replace("writer_ok=128\n", ""), VALID + "role_ok=256\n",
                        VALID + "writer_failure=P000 grant refused\n", VALID + "unrecognized\n"]:
            with self.subTest(text=invalid), self.assertRaises(ValueError):
                runtime.validate_observation(invalid, "OrderSvrA", 128)

    def test_wrong_node_or_non_home_writer_count_rejected(self):
        for node, writers in [("OrderSvrB", 128), ("OrderSvrA", 256), ("OrderSvrA", 0)]:
            with self.subTest(node=node, writers=writers), self.assertRaises(ValueError):
                runtime.validate_observation(VALID, node, writers)

    def test_restart_changes_process_identity(self):
        original = {"Id": "same", "State": {"StartedAt": "before"}, "RestartCount": 0}
        restarted = {"Id": "same", "State": {"StartedAt": "after"}, "RestartCount": 1}
        self.assertNotEqual(runtime.process_identity(original), runtime.process_identity(restarted))


if __name__ == "__main__":
    unittest.main()
