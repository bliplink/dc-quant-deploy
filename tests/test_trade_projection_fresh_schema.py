#!/usr/bin/env python3
"""Regression: a clean MySQL install has every Trade Projection read-model table.

The init SQL and idempotent deploy migration must create identical physical
DDL; these are read-model tables and are NOT a Common cluster implementation.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "mysql/migrations/20261106_trade_projection_financial_readmodel.sql"
INIT = ROOT / "mysql/init/12-trade-projection.sql"
TABLES = (
    "dc_trade_projection_event",
    "dc_trade_projection_mutation",
    "dc_trade_projection_watermark",
    "dc_trade_financial_readmodel_cursor",
)


class TradeProjectionFreshSchemaTest(unittest.TestCase):
    def test_exact_install_deploy_schema_parity(self):
        self.assertEqual(MIGRATION.read_bytes(), INIT.read_bytes())

    def test_four_physical_tables_present_with_idempotent_ddl(self):
        ddl = MIGRATION.read_text()
        names = re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+`?(dc_[a-z_]+)`?", ddl,
            re.IGNORECASE)
        self.assertEqual(list(TABLES), names)

    def test_required_certified_coordinate_columns_and_primary_keys(self):
        ddl = MIGRATION.read_text()
        for table in TABLES:
            m = re.search(
                r"CREATE TABLE IF NOT EXISTS\s+`?" + table +
                r"`?\s*\((.*?)\)\s*ENGINE=InnoDB",
                ddl, re.IGNORECASE | re.DOTALL)
            self.assertIsNotNone(m, table)
            body = m.group(1)
            for column in ("partition_id", "source_epoch", "journal_seq"):
                self.assertIn("`" + column + "`", body, table)
            self.assertIn("PRIMARY KEY", body, table)
        self.assertIn("`mutation_index`", ddl)
        self.assertIn("idx_trade_projection_location", ddl)

    def test_no_reset_or_schema_data_copy(self):
        ddl = MIGRATION.read_text().upper()
        for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE",
                          "RENAME TABLE", "REPLACE INTO", "UPDATE ",
                          "INSERT INTO", "FROM DC_ORDER_PROJECTION"):
            self.assertNotIn(forbidden, ddl)


if __name__ == "__main__":
    unittest.main()