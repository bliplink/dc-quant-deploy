"""T543: guarantee ClickHouse internal logs cannot OOM small Mac Demo again."""
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / 'clickhouse/config.d/30-saas-disable-heavy-system-logs.xml'


class ClickhouseInternalLogsTests(unittest.TestCase):
    def test_large_internal_logs_explicitly_disabled(self):
        root = ET.parse(CFG).getroot()
        self.assertEqual(root.tag, 'clickhouse')
        for table in ['trace_log', 'metric_log', 'asynchronous_metric_log', 'text_log']:
            row = root.find(table)
            self.assertIsNotNone(row)
            self.assertEqual(row.attrib.get('remove'), '1')

    def test_query_and_error_logs_preserved(self):
        root = ET.parse(CFG).getroot()
        self.assertIsNone(root.find('query_log'))
        self.assertIsNone(root.find('error_log'))
        self.assertIsNone(root.find('part_log'))

    def test_compose_persists_config_without_new_images(self):
        text = (ROOT / 'compose.yaml').read_text()
        self.assertIn('./clickhouse/config.d/30-saas-disable-heavy-system-logs.xml:/etc/clickhouse-server/config.d/30-saas-disable-heavy-system-logs.xml:ro', text)
        self.assertIn('CLICKHOUSE_MEMORY_LIMIT:-3072m', text)
        self.assertNotIn('DROP TABLE', CFG.read_text())

    def test_one_click_cleans_only_disabled_internal_logs_after_health(self):
        source = (ROOT / 'deploy-saas.sh').read_text()
        self.assertIn('cleanup_clickhouse_disabled_system_logs() {', source)
        self.assertIn('wait_for_health dc-saas-clickhouse 420\ncleanup_clickhouse_disabled_system_logs', source)
        self.assertIn('DROP TABLE IF EXISTS system.${table} SYNC', source)
        self.assertIn('for table in metric_log asynchronous_metric_log trace_log text_log;', source)
        self.assertNotIn('DROP TABLE dc.', source)


if __name__ == '__main__':
    unittest.main()