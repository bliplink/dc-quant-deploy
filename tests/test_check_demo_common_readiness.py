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

    def test_signed_quorum_census_uses_original_shared_service_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            common = base / "common-demo-original-e1" / "OrderSvr"
            q = common / "sealed" / "P000"
            q.mkdir(parents=True)
            (q / "genesis-e1.quorum").write_bytes(b"for filesystem-only census")
            (q / "genesis-e1.snapshot").write_bytes(b"for filesystem-only census")
            rows = {"P000": {"primary": "OrderSvrA", "replica": "OrderSvrB"}}
            counts = module.count_original("OrderSvr", rows, base)
            self.assertEqual(1, counts["sealed_quorum_present"])
            self.assertEqual(0, counts["rsa_receipts_present"])

    def test_source_config_only_counts_complete_real_partition_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            p = "order.common.nodeRuntime.freshE1."
            required = (
                "primary", "replica", "primaryRsaAlias", "replicaRsaAlias",
                "primaryPhysicalHost", "replicaPhysicalHost", "originalSignedQuorum",
                "localDurableGenesis", "durableTransactionRoot",
                "primaryOriginalWalRoot", "replicaOriginalWalRoot",
            )
            for node in ("A", "B"):
                file = root / f"OrderSvr{node}.properties"
                file.write_text("\n".join(
                    f"{p}P000.{key}=physical-test-value" for key in required
                ) + "\n")
            count = module.count_original_source_config("OrderSvr", root)
            self.assertEqual(1, count["OrderSvrA"]["complete_partition_sources"])
            self.assertEqual(1, count["OrderSvrB"]["complete_partition_sources"])
            (root / "OrderSvrB.properties").write_text("")
            count = module.count_original_source_config("OrderSvr", root)
            self.assertEqual(0, count["OrderSvrB"]["complete_partition_sources"])

    def test_nonmatching_text_not_accepted(self):
        self.assertEqual({}, module.parsed_manifest("P000|1|OrderSvrA|OrderSvrB|ASYNC|READY"))


if __name__ == "__main__":
    unittest.main()
