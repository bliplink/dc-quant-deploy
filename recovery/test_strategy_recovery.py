#!/usr/bin/env python3

import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_live_strategies import build_seed
from strategy_recovery_common import parse_env_file, validate_seed


class StrategyRecoveryTest(unittest.TestCase):
    def test_builds_candidate_import_seed_from_active_rows_only(self):
        source = base64.b64encode(b"public class GeneratedStrategy {}").decode("ascii")
        artifact = base64.b64encode(b"jar").decode("ascii")
        package = {
            "packageType": "live_strategy_backup",
            "exportTime": "2026-08-21 10:00:00",
            "service": "INDSvr",
            "registryRows": [
                {"strategyName": "active_one", "strategyVersion": "v3", "status": "ACTIVE",
                 "scene": "trend", "symbolScope": "BTCUSDT", "textScope": "15m",
                 "effectiveTime": "2026-08-21 09:00:00", "parametersJson": "{}",
                 "payload": "{}"},
                {"strategyName": "offline_one", "strategyVersion": "v1", "status": "OFFLINE"},
            ],
            "candidateRows": [
                {"strategyName": "active_one", "strategyVersion": "v3", "scene": "trend",
                 "javaSourceContentBase64": source, "artifactContentBase64": artifact,
                 "parametersJson": '{"defaultParams":{"period":20},"parameterSchema":{},"optimizationProfile":{}}',
                 "payload": "{}"},
            ],
        }
        seed = build_seed(package)
        strategies = validate_seed(seed)
        self.assertEqual(1, len(strategies))
        self.assertEqual("active_one", strategies[0]["request"]["strategyName"])
        self.assertEqual("IMPORT", strategies[0]["request"]["developmentMode"])
        self.assertEqual("v3", strategies[0]["sourceStrategyVersion"])
        self.assertEqual({"period": 20}, strategies[0]["request"]["defaultParameters"])
        self.assertTrue(strategies[0]["originalArtifactBase64"])

    def test_rejects_direct_restore_policy(self):
        source = base64.b64encode(b"source").decode("ascii")
        package = {
            "packageType": "live_strategy_backup", "registryRows": [
                {"strategyName": "one", "strategyVersion": "v1", "status": "ACTIVE"}],
            "candidateRows": [{"strategyName": "one", "strategyVersion": "v1",
                               "javaSourceContentBase64": source}],
        }
        seed = build_seed(package)
        seed["safetyPolicy"]["directLiveRegistryRestore"] = True
        with self.assertRaises(ValueError):
            validate_seed(seed)


if __name__ == "__main__":
    unittest.main()
