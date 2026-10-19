#!/usr/bin/env python3
"""Read-only Demo schema gate for tenant-created products.

Does not create products, accounts or sessions, and never prints credentials.
"""
import os
import subprocess
import unittest

CONTAINER = os.environ.get("DC_MYSQL_CONTAINER", "dc-saas-mysql")


def query(sql):
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "sh", "-c",
         'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc -e "$1"', "--", sql],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, check=True, timeout=20,
    )
    return [row.split("\t") for row in result.stdout.splitlines()]


class TenantProductSchemaTest(unittest.TestCase):
    def test_product_name_128_is_stored_without_truncation(self):
        rows = query(
            "SELECT TABLE_NAME,COLUMN_NAME,CHARACTER_MAXIMUM_LENGTH "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='dc' AND "
            "((TABLE_NAME='dc_symbol' AND COLUMN_NAME IN "
            "('symbol_en_name','symbol_cn_name')) OR "
            "(TABLE_NAME='dc_tenant_symbol' AND COLUMN_NAME='product_name')) "
            "ORDER BY TABLE_NAME,COLUMN_NAME"
        )
        self.assertEqual(3, len(rows), rows)
        for table, field, length in rows:
            self.assertGreaterEqual(int(length), 128, (table, field, length))

    def test_symbol_identity_remains_tenant_scoped(self):
        rows = query(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA='dc' AND TABLE_NAME='dc_symbol' "
            "AND INDEX_NAME='uq_dc_symbol_tenant_code' AND NON_UNIQUE=0 "
            "AND COLUMN_NAME IN ('location','symbol')"
        )
        self.assertEqual('2', rows[0][0])

    def test_global_templates_survive(self):
        rows = query("SELECT COUNT(*) FROM dc_symbol WHERE location='' ")
        self.assertGreaterEqual(int(rows[0][0]), 1)


if __name__ == "__main__":
    unittest.main()
