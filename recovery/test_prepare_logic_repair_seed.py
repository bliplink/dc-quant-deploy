import base64
import json
import tempfile
import unittest
from pathlib import Path

from prepare_logic_repair_seed import build_seed


class PrepareLogicRepairSeedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Fixed.java").write_text(
            "package com.app.dc.generated.demo.v2; public class Fixed {}\n",
            encoding="utf-8",
        )
        self.base = {
            "packageVersion": "base_v1",
            "strategies": [{
                "strategyName": "demo",
                "sourceStrategyVersion": "v1",
                "sourceSha256": "old",
                "originalArtifactBase64": "artifact",
                "originalArtifactSha256": "artifact-hash",
                "request": {
                    "javaSourceBase64": base64.b64encode(b"old").decode("ascii"),
                    "defaultParameters": {"period": 10},
                    "optimizationProfile": {"mode": "GRID"},
                },
            }],
        }
        self.manifest = {"repairs": [{
            "repairId": "demo_v2",
            "strategyName": "demo",
            "source": "Fixed.java",
            "description": "fixed",
            "logicSummary": "fixed logic",
            "rationale": "test repair",
            "defaultParameters": {"period": 12},
            "optimizationProfile": {"minFitTradesPerSlice": 20},
        }]}

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_versioned_local_only_seed(self):
        result = build_seed(
            self.base, self.manifest, self.root,
            generated_at="2026-10-13T00:00:00+08:00")
        item = result["strategies"][0]
        self.assertEqual("v2", item["sourceStrategyVersion"])
        self.assertEqual("v1", item["request"]["parentVersion"])
        self.assertEqual(12, item["request"]["defaultParameters"]["period"])
        self.assertEqual(20, item["request"]["optimizationProfile"]["minFitTradesPerSlice"])
        self.assertEqual("", item["originalArtifactBase64"])
        self.assertEqual("REVIEW_REQUIRED", item["repairStatus"])
        self.assertFalse(result["safetyPolicy"]["productionWrite"])
        source = base64.b64decode(item["request"]["javaSourceBase64"]).decode()
        self.assertIn(".v2;", source)

    def test_rejects_strategy_missing_from_base_seed(self):
        self.manifest["repairs"][0]["strategyName"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing from base seed"):
            build_seed(self.base, self.manifest, self.root)

    def test_rejects_duplicate_repairs(self):
        self.manifest["repairs"].append(dict(self.manifest["repairs"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate repair"):
            build_seed(self.base, self.manifest, self.root)


if __name__ == "__main__":
    unittest.main()
