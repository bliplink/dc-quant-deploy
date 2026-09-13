import copy
import unittest
from pathlib import Path

from tests.verify_placement_catalogs import load_catalog, resolve_group, validate_catalog


ROOT = Path(__file__).resolve().parents[1] / "control.prod" / "placement"


class PlacementCatalogTest(unittest.TestCase):
    def test_committed_catalogs_match_target_symbol_placement(self):
        order = load_catalog(ROOT / "ordersvr-v1.json")
        md = load_catalog(ROOT / "mdsvr-v1.json")
        self.assertEqual("ORDER_A", resolve_group(order, "WEB_E2E", "4", "BTCUSDT"))
        self.assertEqual("ORDER_B", resolve_group(order, "WEB_E2E", "4", "ETHUSDT"))
        self.assertEqual("ORDER_C", resolve_group(order, "WEB_E2E", "4", "SOLUSDT"))
        self.assertEqual("ORDER_C", resolve_group(order, "NEW_TENANT", "4", "XRPUSDT"))
        self.assertEqual("MD_BTC", resolve_group(md, "WEB_E2E", "4", "BTCUSDT"))
        self.assertEqual("MD_NORMAL", resolve_group(md, "WEB_E2E", "4", "UNIUSDT"))

    def test_rejects_catalog_below_protocol_three(self):
        catalog = load_catalog(ROOT / "ordersvr-v1.json")
        invalid = copy.deepcopy(catalog)
        invalid["protocolVersion"] = 2
        with self.assertRaisesRegex(ValueError, "at least 3"):
            validate_catalog(invalid)


if __name__ == "__main__":
    unittest.main()
