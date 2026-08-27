#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"

log() {
  printf '[location-smoke] %s\n' "$*"
}

die() {
  printf '[location-smoke] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

run_id="$(date +%s)"
location_a="SMOKE_A_${run_id}"
location_b="SMOKE_B_${run_id}"
user_a="smoke_a_${run_id}"
user_b="smoke_b_${run_id}"

mysql_exec() {
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse "$1"
}

clickhouse_exec() {
  docker exec dc-saas-clickhouse clickhouse-client --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" --password "${CLICKHOUSE_PASSWORD}" --query "$1"
}

cleanup() {
  mysql_exec "DELETE FROM dc.dc_users_balance WHERE user_id IN ('${user_a}','${user_b}'); DELETE FROM dc.dc_users WHERE user_id IN ('${user_a}','${user_b}');" >/dev/null 2>&1 || true
  clickhouse_exec "ALTER TABLE dc.kline DELETE WHERE location IN ('${location_a}','${location_b}') SETTINGS mutations_sync=2" >/dev/null 2>&1 || true
}
trap cleanup EXIT

mysql_exec "
  INSERT INTO dc.dc_users (user_id,user_name,password,enable,location)
  VALUES ('${user_a}','${user_a}','smoke-only','1','${location_a}'),
         ('${user_b}','${user_b}','smoke-only','1','${location_b}');
  INSERT INTO dc.dc_users_balance (user_id,account_id,currency,balance,location)
  VALUES ('${user_a}','account-a','USDT',101.25,'${location_a}'),
         ('${user_b}','account-b','USDT',202.50,'${location_b}');
" >/dev/null

count_a="$(mysql_exec "SELECT COUNT(*) FROM dc.dc_users_balance WHERE location='${location_a}' AND user_id='${user_a}' AND balance=101.25;")"
count_b="$(mysql_exec "SELECT COUNT(*) FROM dc.dc_users_balance WHERE location='${location_b}' AND user_id='${user_b}' AND balance=202.50;")"
cross_count="$(mysql_exec "SELECT COUNT(*) FROM dc.dc_users_balance WHERE (location='${location_a}' AND user_id='${user_b}') OR (location='${location_b}' AND user_id='${user_a}');")"

[[ "${count_a}" == "1" && "${count_b}" == "1" && "${cross_count}" == "0" ]] ||
  die "MySQL location isolation failed (A=${count_a}, B=${count_b}, cross=${cross_count})."

start_time="$(date -u '+%Y-%m-%d %H:%M:%S.000000')"
end_time="$(date -u -d '+1 minute' '+%Y-%m-%d %H:%M:%S.000000')"
create_time="$(date -u '+%Y-%m-%d %H:%M:%S.000000')"

clickhouse_exec "
  INSERT INTO dc.kline
    (location,startTime,endTime,securityID,text,fmtTime,open,high,low,close,type,venue,createTime,numTrades,turnover,volume)
  VALUES
    ('${location_a}','${start_time}','${end_time}','BTCUSDT','1M','smoke',100,110,90,105,'','BNFutures','${create_time}',1,10,1),
    ('${location_b}','${start_time}','${end_time}','BTCUSDT','1M','smoke',200,210,190,205,'','BNFutures','${create_time}',1,20,2)
" >/dev/null

kline_a="$(clickhouse_exec "SELECT count() FROM dc.kline_view WHERE location='${location_a}' AND securityID='BTCUSDT' AND open=100")"
kline_b="$(clickhouse_exec "SELECT count() FROM dc.kline_view WHERE location='${location_b}' AND securityID='BTCUSDT' AND open=200")"
kline_cross="$(clickhouse_exec "SELECT count() FROM dc.kline_view WHERE (location='${location_a}' AND open=200) OR (location='${location_b}' AND open=100)")"

[[ "${kline_a}" == "1" && "${kline_b}" == "1" && "${kline_cross}" == "0" ]] ||
  die "ClickHouse location isolation failed (A=${kline_a}, B=${kline_b}, cross=${kline_cross})."

log "MySQL transactional rows are isolated by location."
log "ClickHouse stored the same BTCUSDT/1M key independently for two locations."
log "Two-location smoke test passed; temporary rows will be removed."
