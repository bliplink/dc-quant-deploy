#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
RUN_ID="${ROBOT_E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
LOCATION="${ROBOT_E2E_LOCATION:-ROBOT_E2E_${RUN_ID}}"
ROBOT_USER="${ROBOT_E2E_ROBOT_USER:-robotmaker}"
TRADER_USER="${ROBOT_E2E_TRADER_USER:-robottrader}"
ROBOT_ID="${ROBOT_E2E_ROBOT_ID:-depth10}"
PASSWORD="${ROBOT_E2E_PASSWORD:-$(openssl rand -hex 16)}"

log() { printf '[robot-e2e] %s\n' "$*"; }
die() { printf '[robot-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ "$(id -u)" -eq 0 ]] || die "Run with sudo so the protected environment can be read"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
for value in "${RUN_ID}" "${LOCATION}" "${ROBOT_USER}" "${TRADER_USER}" "${ROBOT_ID}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LOCATION}" == ROBOT_E2E_* ]] || die "ROBOT_E2E_LOCATION must be an isolated ROBOT_E2E_* location"
robot_compact="${ROBOT_ID//[^A-Za-z0-9]/}"
robot_prefix="RB${robot_compact:0:12}-"
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"
command -v openssl >/dev/null || die "openssl is required"
docker inspect dc-saas-robotsvr >/dev/null 2>&1 || die "dc-saas-robotsvr is not deployed"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

api_call() {
  local payload="$1" token="${2:-}"
  if [[ -n "${token}" ]]; then
    curl -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${token}" \
      --data "${payload}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
  else
    curl -fsS --max-time 30 -H 'Content-Type: application/json' \
      --data "${payload}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
  fi
}

json_eval() {
  local expression="$1"
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {"d": d}))' "${expression}"
}

expect_ok() {
  local name="$1" response="$2" code
  code="$(printf '%s' "${response}" | json_eval 'd["code"]')"
  [[ "${code}" == "0" ]] || die "${name} failed: ${response}"
}

wait_for_port() {
  local port="$1" container="$2" start
  start="$(date +%s)"
  until ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${port}$"; do
    if (( $(date +%s) - start >= 120 )); then
      docker logs --tail 120 "${container}" >&2 || true
      die "${container} did not listen on ${port}"
    fi
    sleep 2
  done
}

wait_for_route() {
  local server="$1" start response
  start="$(date +%s)"
  while true; do
    response="$(api_call "{\"serverName\":\"${server}\",\"method\":\"__robot_e2e_readiness__\",\"content\":{}}" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && ! grep -Fq 'is not Online' <<<"${response}"; then return 0; fi
    if (( $(date +%s) - start >= 120 )); then die "${server} did not become routable"; fi
    sleep 2
  done
}

login() {
  local user="$1" response
  response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"SYS.ATS.LOGIN\",\"content\":{\"method\":\"login\",\"cid\":\"ROBOT_LOGIN_${user}\",\"user_id\":\"${user}\",\"user_name\":\"${user}\",\"password\":\"${PASSWORD}\",\"client_type\":\"WEB\",\"Location\":\"${LOCATION}\"}}")"
  expect_ok "login ${user}" "${response}"
  printf '%s' "${response}" | json_eval 'd["data"]["token"]'
}

password_hash="$(printf '%s' "${PASSWORD}" | sha256sum | awk '{print $1}')"
log "Preparing isolated tenant ${LOCATION}."
{
  cat <<SQL
START TRANSACTION;
INSERT INTO dc_tenant
  (location,tenant_code,tenant_name,status,registration_enabled,admin_console_enabled,trade_enabled,
   base_url,default_locale,create_by,update_by,create_time,update_time)
VALUES
  ('${LOCATION}','${LOCATION}','Robot Liquidity E2E','ACTIVE',0,1,1,
   '/#/login?location=${LOCATION}','en-US','robot-e2e','robot-e2e',NOW(),NOW());
INSERT INTO dc_tenant_symbol
  (location,security_id,market_indicator,enabled,tick_size,qty_tick_size,min_order_qty,max_order_qty,
   min_notional,market_take_bound,maker_commission,taker_commission,funding_interval,create_by,update_by,
   create_time,update_time)
VALUES
  ('${LOCATION}','BTCUSDT','4',1,0.01,0.0001,0.0001,10,5,0.05,0.0002,0.0006,28800,
   'robot-e2e','robot-e2e',NOW(),NOW());
INSERT INTO dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${ROBOT_USER}','${ROBOT_USER}','Robot Maker','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-e2e','${LOCATION}'),
  ('${TRADER_USER}','${TRADER_USER}','Robot Test Trader','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-e2e','${LOCATION}');
INSERT INTO dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${ROBOT_USER}',1000000,0,0,0,NOW(),'robot-e2e','${LOCATION}'),
  ('${TRADER_USER}',1000000,0,0,0,NOW(),'robot-e2e','${LOCATION}');
INSERT INTO dc_users_symbol_config
  (user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES
  ('${ROBOT_USER}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-e2e','${LOCATION}','4'),
  ('${TRADER_USER}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-e2e','${LOCATION}','4');
COMMIT;
SQL
} | mysql_exec dc

docker restart dc-saas-loginsvr dc-saas-ordersvr dc-saas-tradesvr >/dev/null
wait_for_port "${LOGINSVR_GW_PORT}" dc-saas-loginsvr
wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
docker restart dc-saas-gateway >/dev/null
wait_for_port "${GW_TCP_PORT}" dc-saas-gateway
wait_for_route LoginSvr
wait_for_route OrderSvr

robot_token="$(login "${ROBOT_USER}")"
trader_token="$(login "${TRADER_USER}")"
key_response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"updateApiKey\",\"content\":{\"cid\":\"ROBOT_KEY_${RUN_ID}\",\"type\":\"trade\",\"inf1\":\"RobotSvr E2E\"}}" "${robot_token}")"
expect_ok "create robot API key" "${key_response}"
robot_api_key="$(printf '%s' "${key_response}" | json_eval 'd["data"]["api_key"]')"
[[ -n "${robot_api_key}" ]] || die "LoginSvr returned no robot API key"

{
  cat <<SQL
INSERT INTO dc_tenant_robot
  (location,robot_id,robot_name,security_id,api_user_id,api_key,quote_source,enabled,bid_levels,ask_levels,
   level_spread_bps,level_step_bps,order_qty,max_position_qty,refresh_interval_ms,stale_price_ms,
   max_deviation_bps,circuit_breaker_seconds,hedge_enabled,strategy_config,runtime_status,
   create_by,update_by,create_time,update_time)
VALUES
  ('${LOCATION}','${ROBOT_ID}','Binance Ticker 10-Level E2E','BTCUSDT','${ROBOT_USER}','${robot_api_key}',
   'APSSVR_BINANCE_TICKER',1,10,10,1,1,0.001,0.1,200,3000,500,5,0,
   JSON_OBJECT('sweep_user_orders_enabled',true,
               'sweep_max_loss_bps',5,'sweep_max_qty',0.001),
   'STOPPED','robot-e2e','robot-e2e',NOW(),NOW());
SQL
} | mysql_exec dc

log "Waiting for APSSvr Binance book ticker and 20 synthesized Robot orders."
ready="0"
for _ in $(seq 1 120); do
  ready="$({
    cat <<SQL
SELECT IF(
  (SELECT runtime_status FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}')='RUNNING'
  AND (SELECT COUNT(*) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'
       AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%'
       AND ord_status IN ('New','Partially_Filled'))=20,
  1,0);
SQL
  } | mysql_exec dc)"
  [[ "${ready}" == "1" ]] && break
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  docker logs --tail 160 dc-saas-robotsvr >&2 || true
  mysql_exec -e "SELECT runtime_status,last_error_code,last_error_message,open_order_count FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >&2 || true
  die "Robot did not reach RUNNING with 20 orders"
fi

compare_ticker_ladder() {
  local robot_file external_file result
  robot_file="$(mktemp)"; external_file="$(mktemp)"
  mysql_exec -e "SELECT side,price FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%' AND ord_status IN ('New','Partially_Filled') ORDER BY side,price" dc >"${robot_file}"
  curl -fsS --max-time 10 'https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol=BTCUSDT' >"${external_file}" || { rm -f "${robot_file}" "${external_file}"; return 1; }
  result="$(python3 - "${robot_file}" "${external_file}" <<'PY'
import json, sys
from decimal import Decimal
rows=[line.rstrip('\n').split('\t') for line in open(sys.argv[1],encoding='utf-8') if line.strip()]
robot_bids=sorted({Decimal(price) for side,price in rows if side.lower()=='buy'}, reverse=True)
robot_asks=sorted({Decimal(price) for side,price in rows if side.lower()=='sell'})
book=json.load(open(sys.argv[2],encoding='utf-8'))
external_mid=(Decimal(book['bidPrice'])+Decimal(book['askPrice']))/2
robot_mid=(robot_bids[0]+robot_asks[0])/2 if robot_bids and robot_asks else Decimal(0)
deviation_bps=abs(robot_mid-external_mid)*Decimal(10000)/external_mid
monotonic=(len(robot_bids)==10 and len(robot_asks)==10
           and all(robot_bids[i]>robot_bids[i+1] for i in range(9))
           and all(robot_asks[i]<robot_asks[i+1] for i in range(9))
           and robot_bids[0] < robot_asks[0])
print(len(robot_bids),len(robot_asks),int(monotonic),deviation_bps)
PY
)"
  rm -f "${robot_file}" "${external_file}"
  read -r robot_bids robot_asks monotonic deviation_bps <<<"${result}"
  python3 - "${robot_bids}" "${robot_asks}" "${monotonic}" "${deviation_bps}" <<'PY'
from decimal import Decimal
import sys
bids,asks,monotonic=sys.argv[1:4]
assert bids=='10' and asks=='10' and monotonic=='1'
assert Decimal(sys.argv[4]) <= Decimal('30')
PY
}

ticker_ladder_ok="0"
for _ in $(seq 1 30); do
  if compare_ticker_ladder; then ticker_ladder_ok="1"; break; fi
  sleep 1
done
[[ "${ticker_ladder_ok}" == "1" ]] || die "Robot did not synthesize a valid 10+10 ladder near the live Binance book ticker"
log "Binance ticker ladder passed: 10 distinct bids + 10 distinct asks, ordered and within 30 bps of live midpoint."

log "Hitting a Robot ask and verifying the partially filled level is replenished."
robot_filled_before="$(mysql_exec -e "SELECT COALESCE(SUM(cum_qty),0) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%'" dc)"
hit_ok="0"
hit_clid=""
for attempt in $(seq 1 20); do
  current_ask="$(mysql_exec -e "SELECT MIN(price) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%' AND side='Sell' AND ord_status IN ('New','Partially_Filled')" dc)"
  [[ -n "${current_ask}" && "${current_ask}" != "NULL" ]] || { sleep 1; continue; }
  hit_clid="ROBOT-HIT-${RUN_ID}-${attempt}"
  hit_response="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${hit_clid}\",\"Terminal\":\"RobotE2E\",\"AlgoName\":\"robot-e2e-hit\",\"Side\":\"Buy\",\"Price\":\"${current_ask}\",\"UserID\":\"${TRADER_USER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"IOC\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${trader_token}" 2>/dev/null || true)"
  if [[ -z "${hit_response}" ]] || [[ "$(printf '%s' "${hit_response}" | json_eval 'd.get("code",-1)' 2>/dev/null || true)" != "0" ]]; then
    sleep 1
    continue
  fi
  for _ in $(seq 1 20); do
    hit_ok="$(mysql_exec -e "SELECT IF(
      (SELECT ord_status FROM dc_orders WHERE location='${LOCATION}' AND clord_id='${hit_clid}')='Filled'
      AND (SELECT COALESCE(SUM(cum_qty),0) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%') >= ${robot_filled_before}+0.0001,
      1,0)" dc)"
    [[ "${hit_ok}" == "1" ]] && break 2
    sleep 0.5
  done
done
[[ "${hit_ok}" == "1" ]] || die "User IOC did not hit a Robot ask after 20 live-book attempts"

replenished="0"
for _ in $(seq 1 60); do
  replenished="$(mysql_exec -e "SELECT IF(
    (SELECT COUNT(*) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'
      AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%'
      AND ord_status IN ('New','Partially_Filled'))=20
    AND (SELECT COUNT(*) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'
      AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%'
      AND ord_status IN ('New','Partially_Filled')
      AND COALESCE(leaves_qty,0)<>COALESCE(order_qty,0))=0,
    1,0)" dc)"
  [[ "${replenished}" == "1" ]] && break
  sleep 1
done
[[ "${replenished}" == "1" ]] || die "Robot did not replenish all 20 quote levels after a user fill"
log "User hit and full 10+10 level replenishment passed (${hit_clid})."

read -r best_bid best_ask <<<"$(mysql_exec -e "SELECT MAX(CASE WHEN side='Buy' THEN price END),MIN(CASE WHEN side='Sell' THEN price END) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%' AND ord_status='New'" dc)"
inside_price="$(python3 - "${best_bid}" "${best_ask}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
bid,ask=map(Decimal,sys.argv[1:])
assert ask-bid >= Decimal('0.02')
price=((bid+ask)/2).quantize(Decimal('0.01'),rounding=ROUND_DOWN)
if price <= bid: price=bid+Decimal('0.01')
if price >= ask: price=ask-Decimal('0.01')
print(price)
PY
)" || die "The live spread has no tenant-tick price inside it"

clid="ROBOT-SWEEP-${RUN_ID}"
place_response="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"RobotE2E\",\"AlgoName\":\"robot-e2e-user\",\"Side\":\"Sell\",\"Price\":\"${inside_price}\",\"UserID\":\"${TRADER_USER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${trader_token}")"
expect_ok "place inside-spread user order" "${place_response}"

sweep_ok="0"
for _ in $(seq 1 60); do
  sweep_ok="$({
    cat <<SQL
SELECT IF(
  (SELECT ord_status FROM dc_orders WHERE location='${LOCATION}' AND clord_id='${clid}')='Filled'
  AND EXISTS (SELECT 1 FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'
              AND clord_id LIKE '${robot_prefix}%-SW%' AND side='Buy' AND ord_status='Filled')
  AND EXISTS (SELECT 1 FROM dc_orders_position WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'
              AND security_id='BTCUSDT' AND long_position>=0.0001)
  AND EXISTS (SELECT 1 FROM dc_orders_position WHERE location='${LOCATION}' AND user_id='${TRADER_USER}'
              AND security_id='BTCUSDT' AND short_position>=0.0001),
  1,0);
SQL
  } | mysql_exec dc)"
  [[ "${sweep_ok}" == "1" ]] && break
  sleep 1
done
[[ "${sweep_ok}" == "1" ]] || die "Robot did not consume the inside-spread user order"
log "User order was consumed by Robot IOC and both positions were persisted."

mysql_exec -e "UPDATE dc_tenant_robot SET enabled=0,update_by='robot-e2e',update_time=NOW() WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >/dev/null
stopped="0"
for _ in $(seq 1 60); do
  stopped="$({
    cat <<SQL
SELECT IF(
  (SELECT runtime_status FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}')='STOPPED'
  AND (SELECT COUNT(*) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'
       AND clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%'
       AND ord_status IN ('New','Partially_Filled','Pending_Cancel'))=0,
  1,0);
SQL
  } | mysql_exec dc)"
  [[ "${stopped}" == "1" ]] && break
  sleep 1
done
[[ "${stopped}" == "1" ]] || die "Disabling Robot did not cancel all live quotes"

summary="$(mysql_exec -e "SELECT CONCAT('quotes=',SUM(clord_id LIKE '${robot_prefix}%' AND clord_id NOT LIKE '${robot_prefix}%-SW%'),',sweeps=',SUM(clord_id LIKE '${robot_prefix}%-SW%'),',fills=',SUM(ord_status='Filled')) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}'; SELECT CONCAT('executions=',COUNT(*)) FROM dc_orders_execorders WHERE location='${LOCATION}' AND user_id IN ('${ROBOT_USER}','${TRADER_USER}'); SELECT CONCAT('foreign_location_orders=',COUNT(*)) FROM dc_orders WHERE location<>'${LOCATION}' AND clord_id LIKE '%${RUN_ID}%';" dc)"
grep -Fq 'foreign_location_orders=0' <<<"${summary}" || die "Robot E2E order identifiers leaked into another location"
log "PASS: ${summary//$'\n'/; }."
log "Evidence location retained: ${LOCATION}; hedge remained disabled because no external Binance credential was supplied."
