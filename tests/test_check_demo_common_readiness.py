#!/usr/bin/env python3
"""Read-only manifest parser contract tests. No Docker or real credentials."""
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "common_demo_check", str(HERE / "check-demo-common-readiness.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManifestSafetyTest(unittest.TestCase):
    def test_strict_e1_nonroutable_parses(self):
        raw = "NPC1|1\nP000|1|OrderSvrA|OrderSvrB|STRICT_QUORUM|RECOVERING"
        rows = module.parsed_manifest(raw)
        self.assertEqual(1, rows["P000"]["epoch"])
        self.assertEqual("RECOVERING", rows["P000"]["phase"])

    def test_duplication_fails_closed(self):
        row = "P090|1|TradeSvrA|TradeSvrB|STRICT_QUORUM|RECOVERING"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            module.parsed_manifest(row + "\n" + row)

    def test_same_voter_fails_closed(self):
        row = "P012|1|TradeSvrA|TradeSvrA|STRICT_QUORUM|RECOVERING"
        with self.assertRaisesRegex(ValueError, "non-independent"):
            module.parsed_manifest(row)

    def test_nonmatching_text_not_accepted(self):
        self.assertEqual({}, module.parsed_manifest("P000|1|OrderSvrA|OrderSvrB|ASYNC|READY"))


if __name__ == "__main__":
    unittest.main()
