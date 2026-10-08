"""Safe non-destructive ClickHouse system-log configuration for the demo VM."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "clickhouse" / "config.d" / "90-saas-demo-quiet.xml"
COMPOSE = ROOT / "compose.yaml"
DISABLED = {
    "trace_log", "text_log", "metric_log",
    "asynchronous_metric_log", "processors_profile_log",
}
PRESERVED = {"query_log", "error_log", "part_log", "crash_log"}


class ClickhouseDemoLogConfigTest(unittest.TestCase):
    def test_xml_is_valid_and_disables_only_expected_tables(self):
        root = ET.parse(str(PROFILE)).getroot()
        self.assertEqual("clickhouse", root.tag)
        self.assertEqual(DISABLED, {child.tag for child in root})
        for child in root:
            self.assertEqual("1", child.attrib.get("remove"))
            self.assertFalse(list(child))
        self.assertTrue(PRESERVED.isdisjoint({child.tag for child in root}))

    def test_mount_is_read_only_and_preserves_data_volume(self):
        data = COMPOSE.read_text(encoding="utf-8")
        target = ("./clickhouse/config.d/90-saas-demo-quiet.xml:"
                  "/etc/clickhouse-server/config.d/90-saas-demo-quiet.xml:ro")
        self.assertEqual(1, data.count(target))
        self.assertIn("${DEPLOY_ROOT}/data/clickhouse:/var/lib/clickhouse", data)

    def test_no_destructive_log_table_sql(self):
        text = PROFILE.read_text(encoding="utf-8").lower()
        for command in ("drop table", "truncate table", "alter table", "optimize table"):
            self.assertNotIn(command, text.replace("not dropped, truncated or mutated", ""))


if __name__ == "__main__":
    unittest.main()
