# Database

## Boundary

The public deployment only uses ClickHouse.

- there is no MySQL in this repository
- Java services should point only to ClickHouse
- `DBPoolConfig.ini` in both template sets only contains ClickHouse settings

## Bootstrap Layout

- `clickhouse/init/00-create-db.sql`
- `clickhouse/init/01-run-all.sh`
- `clickhouse/init/10-schema/`
- `clickhouse/init/20-view/`
- `clickhouse/init/90-optional-seed/`

## Default Bootstrap Behavior

On first startup, the official ClickHouse image runs `docker-entrypoint-initdb.d`.

This repository uses that hook to:

1. create database `dc` if needed
2. apply all SQL in `10-schema/`
3. apply all SQL in `20-view/`

Files under `90-optional-seed/` are intentionally excluded from automatic bootstrap.

## Core Schema

The default schema set includes tables for:

- `signal`
- `quant_*`
- `kline`
- `backtest_*`
- `strategy_*`

Core readiness in deployment validation is based on these tables:

- `dc.signal`
- `dc.quant_order`
- `dc.strategy_candidate`

## Optional SQL

The following files are kept for operator-controlled execution only:

- `builtin_migration_seed_20260402.sql`
- `reset_all_except_kline_20260419.sql`
- `source_aware_builtin_checks.sql`
- `source_aware_builtin_cleanup.sql`
- `source_aware_checks.sql`
- `source_aware_cleanup_stale_backtest_task_20260411.sql`
- `source_aware_sample_cleanup.sql`

They are not safe as unconditional startup SQL because they include migration, cleanup, verification, or environment-specific actions.

## Idempotency Rule

The repository expects the default bootstrap SQL to be repeatable.

Current convention:

- `CREATE DATABASE IF NOT EXISTS`
- `CREATE TABLE IF NOT EXISTS`
- `CREATE VIEW IF NOT EXISTS`

If you add new DDL later, keep the same rule so the init sequence remains rerunnable.

## Manual Rerun

If you need to rerun the default schema bootstrap manually:

```bash
docker compose exec -T clickhouse /docker-entrypoint-initdb.d/01-run-all.sh
```
