"""Keep Order binary-projection batch-watermark rewrite opt-in on SaaS demo.

This test is deliberately static. It does not connect to MySQL or mutate
journal/offset data, and can run in the deployment CI environment.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "generate-saas-configs.sh"
SETTING = ("projection.order.binary.watermarkBatchOptimized="
           "${PROJECTION_ORDER_WATERMARK_BATCH_OPTIMIZED:-false}")


class ProjectionWatermarkOptInTest(unittest.TestCase):
    def test_generator_never_turns_on_batch_watermark_implicitly(self):
        text = GENERATOR.read_text(encoding="utf-8")
        self.assertEqual(1, text.count(SETTING))
        self.assertNotIn("projection.order.binary.watermarkBatchOptimized=true", text)
        self.assertIn("projection.binary.enabled=${ORDER_CLUSTER_ENABLED}", text)
        self.assertIn("projection.trade.binary.enabled=${TRADE_CLUSTER_ENABLED}", text)

    def test_env_override_has_only_fail_closed_false_fallback(self):
        text = GENERATOR.read_text(encoding="utf-8")
        self.assertNotIn("PROJECTION_ORDER_WATERMARK_BATCH_OPTIMIZED:-true", text)
        self.assertIn("projection.binary.workerStripes=4", text)


if __name__ == "__main__":
    unittest.main()
