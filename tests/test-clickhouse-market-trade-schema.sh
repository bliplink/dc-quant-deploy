#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
sql=clickhouse/saas-init/15-market-trade.sql
test -f "$sql"
grep -Fq 'CREATE TABLE IF NOT EXISTS dc.market_trade' "$sql"
grep -Fq 'ENGINE = MergeTree()' "$sql"
grep -Fq 'TTL createTime + INTERVAL 30 DAY DELETE' "$sql"
! grep -Eq 'DROP TABLE|TRUNCATE TABLE|ALTER TABLE.*DELETE' "$sql"
for field in location transactTime securityID marketIndicator execID price quantity amount createTime; do
  grep -Fq "\`$field\`" "$sql" || { echo "missing MarketTrade field $field" >&2; exit 1; }
done
echo '[market-trade-ddl] PASS nine fields, append-only engine, idempotent safe DDL'
