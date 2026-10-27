#!/usr/bin/env python3
"""Fail fast if fresh one-click MySQL misses the live tenant/Robot schema.

The first 2026-10-27 empty reinstall had 54 tables and ran every migration
successfully, but an omitted tracked migration made every auto-approved
application silently roll back. This check is read-only, password-safe and
must run before tenant registration / activating the Robot worker.
"""
import os
import subprocess
import sys

EXPECTED = {
    "dc_tenant": {"location", "status", "liquidity_source", "source_switch_state"},
    "dc_tenant_application": {"application_id", "status", "approved_location"},
    "dc_tenant_symbol": {"location", "security_id", "data_source_id", "product_name", "enabled"},
    "dc_tenant_data_source": {
        "location", "data_source_id", "source_name", "source_type",
        "source_symbol", "enabled", "create_by", "update_by", "create_time", "update_time"
    },
    "dc_tenant_liquidity_bootstrap": {
        "application_id", "location", "status", "step", "maker_user_id",
        "funding_confirmed", "next_attempt_time", "last_error_code"
    },
    "dc_tenant_robot": {"location", "robot_id", "runtime_status", "open_order_count"},
}

def fetch_columns():
    query = (
        "SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA='dc' ORDER BY TABLE_NAME,COLUMN_NAME"
    )
    dbport = os.environ.get("MYSQL_PORT", "3306")
    if not dbport.isdigit() or not 1 <= int(dbport) <= 65535:
        raise RuntimeError("invalid MySQL port")
    command = [
        "docker", "exec", "-e", "MYSQL_PWD=" + os.environ["MYSQL_ROOT_PASSWORD"],
        "dc-saas-mysql", "mysql", "--protocol=TCP", "-h127.0.0.1",
        "-P" + dbport, "-uroot", "-N", "-B", "-e", query,
    ]
    result = subprocess.run(command, check=True, capture_output=True,
                            text=True, timeout=30)
    tables = {}
    for line in result.stdout.splitlines():
        name, column = line.split("\t", 1)
        tables.setdefault(name, set()).add(column)
    return tables

def main():
    if not os.environ.get("MYSQL_ROOT_PASSWORD"):
        raise RuntimeError("MYSQL_ROOT_PASSWORD not set by one-click deploy")
    existing = fetch_columns()
    missing = {
        table: sorted(columns - existing.get(table, set()))
        for table, columns in EXPECTED.items()
        if columns - existing.get(table, set())
    }
    if missing:
        for table, columns in sorted(missing.items()):
            print("T172_FRESH_TENANT_SCHEMA_NO_GO", table, ",".join(columns), file=sys.stderr)
        raise SystemExit(2)
    print("T172_FRESH_TENANT_AUTO_APPROVAL_AND_ROBOT_SCHEMA_PASS "
          f"tables={len(EXPECTED)} columns={sum(map(len, EXPECTED.values()))}")

if __name__ == "__main__":
    try:
        main()
    except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as exc:
        print("T172_FRESH_TENANT_SCHEMA_CHECK_ERROR", type(exc).__name__, file=sys.stderr)
        sys.exit(3)