#!/usr/bin/env bash
# Read-only verification of ClickHouse market-trade persistence.
# Explicitly separate append-only market-data storage from Order/Trade Projection.
set -euo pipefail

CH_CONTAINER="${MARKET_TRADE_CH_CONTAINER:-dc-saas-clickhouse}"
MD_CONTAINER="${MARKET_TRADE_MD_CONTAINER:-dc-saas-mdsvr}"
MAX_AGE_SECONDS="${MARKET_TRADE_MAX_AGE_SECONDS:-180}"
MIN_TENANTS="${MARKET_TRADE_MIN_TENANTS:-1}"
LOG_WINDOW="${MARKET_TRADE_ERROR_WINDOW:-90s}"

[[ "${MIN_TENANTS}" =~ ^[1-9][0-9]*$ ]] || {
  echo '[market-trade-check] FAIL invalid MARKET_TRADE_MIN_TENANTS' >&2; exit 2;
}
[[ "${MAX_AGE_SECONDS}" =~ ^[1-9][0-9]*$ ]] || {
  echo '[market-trade-check] FAIL invalid MAX_AGE_SECONDS' >&2; exit 2;
}
[[ "${LOG_WINDOW}" =~ ^[1-9][0-9]*[smh]$ ]] || {
  echo '[market-trade-check] FAIL invalid ERROR_WINDOW' >&2; exit 2;
}

table_exists="$(docker exec "${CH_CONTAINER}" clickhouse-client --query 'EXISTS TABLE dc.market_trade')"
[[ "${table_exists}" == '1' ]] || { echo '[market-trade-check] FAIL missing dc.market_trade' >&2; exit 1; }

# Decimal and timestamp contract is checked by the insert-enabled production service.
data="$(docker exec "${CH_CONTAINER}" clickhouse-client --format=TabSeparatedRaw --query "
 SELECT count(), uniqExact(location),
 if(count() = 0, 999999, dateDiff('second',max(createTime),now()))
 FROM dc.market_trade
")"
IFS=$'\t' read -r total tenant_count newest_age <<<"${data}"
[[ "${total}" =~ ^[0-9]+$ && "${tenant_count}" =~ ^[0-9]+$ && "${newest_age}" =~ ^[0-9]+$ ]] || {
  echo '[market-trade-check] FAIL could not parse ClickHouse persistence response' >&2; exit 1;
}
echo "[market-trade-check] INFO persisted_rows=${total} tenant_locations=${tenant_count} newest_age_seconds=${newest_age}"
(( total > 0 )) || { echo '[market-trade-check] FAIL no persisted market trades yet' >&2; exit 1; }
(( tenant_count >= MIN_TENANTS )) || {
  echo "[market-trade-check] FAIL tenant_locations=${tenant_count} expected_minimum=${MIN_TENANTS}" >&2; exit 1;
}
(( newest_age <= MAX_AGE_SECONDS )) || {
  echo "[market-trade-check] FAIL market-trade storage stale (max ${MAX_AGE_SECONDS}s)" >&2; exit 1;
}

error_count="$(docker logs --since "${LOG_WINDOW}" "${MD_CONTAINER}" 2>&1 |
  grep -c 'ERROR BatchClickHouseTask:market_trade' || true)"
echo "[market-trade-check] INFO mdsvr_batch_errors=${error_count} window=${LOG_WINDOW}"
(( error_count == 0 )) || {
  echo '[market-trade-check] FAIL recent MDSvr market_trade batch errors' >&2; exit 1;
}
echo '[market-trade-check] PASS dc.market_trade present, fresh and no recent MDSvr batch failure'
