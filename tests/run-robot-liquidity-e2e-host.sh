#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
RUN_ID="${ROBOT_E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
LOCATION="${ROBOT_E2E_LOCATION:-ROBOT_E2E_${RUN_ID}}"
ROBOT_USER="${ROBOT_E2E_ROBOT_USER:-robotmaker}"
TRADER_USER="${ROBOT_E2E_TRADER_USER:-robottrader}"
TAPE_USER="${ROBOT_E2E_TAPE_USER:-robottape}"
ROBOT_ID="${ROBOT_E2E_ROBOT_ID:-depth10}"
PASSWORD="${ROBOT_E2E_PASSWORD:-$(openssl rand -hex 16)}"

# Local GW/MySQL/management calls must never be sent through an inherited
# host/VM HTTP proxy. Keep external proxy settings untouched, but always bypass
# them for loopback traffic used by this acceptance test.
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="${NO_PROXY}"

log() { printf '[robot-e2e] %s\n' "$*"; }
die() { printf '[robot-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}; run with sufficient permission"
for value in "${RUN_ID}" "${LOCATION}" "${ROBOT_USER}" "${TRADER_USER}" "${TAPE_USER}" "${ROBOT_ID}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LOCATION}" == ROBOT_E2E_* ]] || die "ROBOT_E2E_LOCATION must be an isolated ROBOT_E2E_* location"
[[ "${TAPE_USER}" != "${ROBOT_USER}" && "${TAPE_USER}" != "${TRADER_USER}" ]] || die "Tape user must be distinct from maker and test trader"
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
  until [[ "$(docker inspect --format '{{.State.Running}}' "${container:-${service}}" 2>/dev/null || true)" == "true" ]]; do
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
    if [[ -n "${response}" ]] && ! grep -Eq 'is not Online|PARTITION_NOT_READY|STALE_PARTITION' <<<"${response}"; then return 0; fi
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

fund_trade_account() {
  local user="$1" token="$2" demo="$3" response
  response="$(api_call "{\"serverName\":\"TradeSvr\",\"method\":\"cashIn\",\"key\":\"${LOCATION}\",\"content\":{\"Amount\":\"1000000\",\"UserID\":\"${user}\",\"Location\":\"${LOCATION}\",\"Demo\":\"${demo}\"}}" "${token}")"
  expect_ok "fund TradeSvr runtime account ${user}" "${response}"
}

password_hash="$(printf '%s' "${PASSWORD}" | sha256sum | awk '{print $1}')"
log "Preparing isolated tenant ${LOCATION}."
# Keep this deterministic acceptance isolated from stale workers left by a prior
# failed run. RobotSvr polls enabled rows, so disable older ROBOT_E2E fixtures
# before inserting the current one.
mysql_exec -e "UPDATE dc_tenant_robot SET enabled=0,update_by='robot-e2e-cleanup',update_time=NOW() WHERE location LIKE 'ROBOT_E2E\_%' AND location<>'${LOCATION}' AND enabled=1" dc >/dev/null
# Let the supervisor remove the prior same-symbol worker before replacement.
sleep 4
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
  ('${LOCATION}','BTCUSDT','4',1,0.1,0.0001,0.0001,10,5,0.05,0.0002,0.0006,28800,
   'robot-e2e','robot-e2e',NOW(),NOW());
INSERT INTO dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${ROBOT_USER}','${ROBOT_USER}','Robot Maker','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-e2e','${LOCATION}'),
  ('${TRADER_USER}','${TRADER_USER}','Robot Test Trader','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-e2e','${LOCATION}'),
  ('${TAPE_USER}','${TAPE_USER}','Robot Tape Trader','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-e2e','${LOCATION}');
INSERT INTO dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${ROBOT_USER}',0,0,0,0,NOW(),'robot-e2e','${LOCATION}'),
  ('${TRADER_USER}',0,0,0,0,NOW(),'robot-e2e','${LOCATION}'),
  ('${TAPE_USER}',0,0,0,0,NOW(),'robot-e2e','${LOCATION}');
INSERT INTO dc_users_symbol_config
  (user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES
  ('${ROBOT_USER}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-e2e','${LOCATION}','4'),
  ('${TRADER_USER}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-e2e','${LOCATION}','4'),
  ('${TAPE_USER}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-e2e','${LOCATION}','4');
COMMIT;
SQL
} | mysql_exec dc

# Robot acceptance runs against the already-online trading fabric. Restarting
# Login/Order/Trade/GW here creates an artificial route outage that production
# Robot configuration changes must not require.
# Use the real login/order/trade calls below as readiness gates. The gateway
# maps unknown-method probes to HTTP 503, so synthetic __robot_e2e_readiness__
# calls can falsely report a route outage even while the service is online.
for _ in $(seq 1 90); do
  response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"SYS.ATS.LOGIN\",\"content\":{\"method\":\"login\",\"cid\":\"ROBOT_LOGIN_${ROBOT_USER}\",\"user_id\":\"${ROBOT_USER}\",\"user_name\":\"${ROBOT_USER}\",\"password\":\"${PASSWORD}\",\"client_type\":\"WEB\",\"Location\":\"${LOCATION}\"}}" 2>/dev/null || true)"
  if [[ -n "${response}" ]] && python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("code")==0 and d.get("data",{}).get("token") else 1)' <<<"${response}" 2>/dev/null; then
    robot_token="$(printf '%s' "${response}" | json_eval 'd["data"]["token"]')"
    break
  fi
  sleep 2
done
[[ -n "${robot_token:-}" ]] || die "LoginSvr did not become usable through GW"
trader_token="$(login "${TRADER_USER}")"
tape_token="$(login "${TAPE_USER}")"

# Direct SQL only creates the durable account shells. TradeSvr owns hot
# balance state, so publish funding through the clustered mutation path before
# RobotSvr starts quoting. Robot/tape are internal Demo=1 identities; the test
# trader remains normal Demo=0 business flow.
fund_trade_account "${ROBOT_USER}" "${robot_token}" "1"
fund_trade_account "${TRADER_USER}" "${trader_token}" "0"
fund_trade_account "${TAPE_USER}" "${tape_token}" "1"

robot_open_orders() {
  api_call "{\"serverName\":\"OrderSvr\",\"method\":\"queryOpenOrder\",\"key\":\"${LOCATION}\\u001f4\\u001fBTCUSDT\",\"content\":{\"securityid\":\"BTCUSDT\",\"userid\":\"${ROBOT_USER}\",\"Location\":\"${LOCATION}\"}}" "${robot_token}"
}

robot_open_value() {
  local expression="$1"
  python3 -c '
import json,sys
d=json.load(sys.stdin)
assert int(d.get("code",-1)) == 0, d
prefix=sys.argv[2]
rows=[]
for row in d.get("data") or []:
    item={str(k).lower().replace("_",""):v for k,v in row.items()}
    cid=str(item.get("clordid") or "")
    status=str(item.get("ordstatus") or "").strip().replace("-","_").replace(" ","_")
    active=status in ("0","1") or status.lower() in ("new","partially_filled")
    if cid.startswith(prefix) and "-SW" not in cid and active:
        rows.append(item)
print(eval(sys.argv[1], {"rows":rows}))
' "${expression}" "${robot_prefix}"
}

key_response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"updateApiKey\",\"content\":{\"cid\":\"ROBOT_KEY_${RUN_ID}\",\"type\":\"trade\",\"inf1\":\"RobotSvr E2E\"}}" "${robot_token}")"
expect_ok "create robot API key" "${key_response}"
robot_api_key="$(printf '%s' "${key_response}" | json_eval 'd["data"]["api_key"]')"
[[ -n "${robot_api_key}" ]] || die "LoginSvr returned no robot API key"

tape_key_response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"updateApiKey\",\"content\":{\"cid\":\"ROBOT_TAPE_KEY_${RUN_ID}\",\"type\":\"trade\",\"inf1\":\"RobotSvr Binance volume tape E2E\"}}" "${tape_token}")"
expect_ok "create tape API key" "${tape_key_response}"
tape_api_key="$(printf '%s' "${tape_key_response}" | json_eval 'd["data"]["api_key"]')"
[[ -n "${tape_api_key}" ]] || die "LoginSvr returned no tape API key"

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
               'sweep_max_loss_bps',5,'sweep_max_qty',0.001,
               'tape_enabled',false,'tape_api_user_id','${TAPE_USER}','tape_api_key','${tape_api_key}',
               'tape_volume_scale',0.01,'tape_min_notional',5,'tape_max_notional',1000,
               'tape_interval_ms',1000),
   'STOPPED','robot-e2e','robot-e2e',NOW(),NOW());
SQL
} | mysql_exec dc

# RobotSvr polls durable configuration every ROBOT_CONFIG_POLL_MS (3s by
# default). The runtime_status/open-order loop below is the real hot-discovery
# readiness gate; do not use a synthetic unknown-method probe here.
log "Waiting for RobotSvr hot reconciliation of the current fixture."

log "Waiting for APSSvr Binance book ticker and 20 synthesized Robot orders."
ready="0"
for _ in $(seq 1 120); do
  read -r runtime_status runtime_open_count <<<"$(mysql_exec -e "SELECT runtime_status,open_order_count FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc)"
  open_response="$(robot_open_orders 2>/dev/null || true)"
  read -r live_bids live_asks <<<"$(printf '%s' "${open_response}" | robot_open_value 'str(len({str(row.get("price")) for row in rows if str(row.get("side","")).lower()=="buy"}))+" "+str(len({str(row.get("price")) for row in rows if str(row.get("side","")).lower()=="sell"}))' 2>/dev/null || true)"
  [[ "${runtime_status}" == "RUNNING" && "${runtime_open_count}" == "20" && "${live_bids:-0}" == "10" && "${live_asks:-0}" == "10" ]] && ready="1" || ready="0"
  [[ "${ready}" == "1" ]] && break
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  docker logs --tail 160 dc-saas-robotsvr >&2 || true
  mysql_exec -e "SELECT runtime_status,last_error_code,last_error_message,open_order_count FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >&2 || true
  die "Robot did not reach RUNNING with an acknowledged 20-order target and stable 10+10 ladder"
fi


# First prove the pure quoting book while Tape is off. Tape intentionally consumes
# quote liquidity and would make a simultaneous exact 10+10 assertion racy.
compare_ticker_ladder() {
  local robot_file result reference_price
  robot_file="$(mktemp)"
  robot_open_orders >"${robot_file}"
  reference_price="$(mysql_exec -e "SELECT COALESCE(last_reference_price,0) FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}' LIMIT 1;" dc 2>/dev/null || echo 0)"
  result="$(python3 - "${robot_file}" "${reference_price}" <<'PY'
import json, sys
from decimal import Decimal
response=json.load(open(sys.argv[1],encoding='utf-8'))
rows=[{str(k).lower().replace('_',''):v for k,v in row.items()} for row in response.get('data') or []]
robot_bids=sorted({Decimal(str(row.get('price'))) for row in rows if str(row.get('side','')).lower()=='buy'}, reverse=True)
robot_asks=sorted({Decimal(str(row.get('price'))) for row in rows if str(row.get('side','')).lower()=='sell'})
external_mid=Decimal(sys.argv[2])
if external_mid <= 0:
    raise SystemExit(1)
robot_mid=(robot_bids[0]+robot_asks[0])/2 if robot_bids and robot_asks else Decimal(0)
deviation_bps=abs(robot_mid-external_mid)*Decimal(10000)/external_mid
monotonic=(len(robot_bids)==10 and len(robot_asks)==10
           and all(robot_bids[i]>robot_bids[i+1] for i in range(9))
           and all(robot_asks[i]<robot_asks[i+1] for i in range(9))
           and robot_bids[0] < robot_asks[0])
print(len(robot_bids),len(robot_asks),int(monotonic),deviation_bps)
PY
)"
  rm -f "${robot_file}"
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
log "Binance ticker ladder passed: stable 10 bids + 10 asks, ordered and within 30 bps of the APSSvr Binance reference."

log "Enabling Binance-volume Tape after the stable ladder passed."
mysql_exec -e "UPDATE dc_tenant_robot SET strategy_config=JSON_SET(strategy_config,'$.tape_enabled',CAST('true' AS JSON)),update_by='robot-e2e-tape-on',update_time=NOW() WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >/dev/null

log "Waiting for Binance-volume Tape to produce a tenant K-line."
tape_ready="0"
tape_close="0"
tape_volume="0"
tape_deviation_bps="999999"
for _ in $(seq 1 60); do
  # Historical K-line is served by AdminSvr/ClickHouse. MDSvr is the live
  # subscription path and must not be used as the historical query backend.
  kline_response="$(api_call "{\"serverName\":\"AdminSvr\",\"method\":\"queryKLine\",\"content\":{\"num\":10,\"securityID\":\"BTCUSDT\",\"text\":\"1M\",\"Location\":\"${LOCATION}\",\"location\":\"${LOCATION}\"}}" 2>/dev/null || true)"
  reference_price="$(mysql_exec -e "SELECT COALESCE(last_reference_price,0) FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}' LIMIT 1;" dc 2>/dev/null || echo 0)"
  read -r tape_ready tape_close tape_volume tape_deviation_bps <<<"$(printf '%s' "${kline_response}" | python3 -c '
import json,sys
from decimal import Decimal
try:
    d=json.load(sys.stdin)
    rows=d.get("data") if isinstance(d.get("data"),list) else ((d.get("data") or {}).get("data") or [])
    ref=Decimal(sys.argv[1])
    if int(d.get("code",-1)) != 0 or not rows or ref <= 0:
        print("0 0 0 999999")
        raise SystemExit
    parts=str(rows[-1]).split(",")
    close=Decimal(parts[5]); volume=Decimal(parts[6])
    deviation=abs(close-ref)*Decimal(10000)/ref
    print(1 if close > 0 and volume > 0 and deviation <= Decimal("100") else 0,
          close, volume, deviation)
except Exception:
    print("0 0 0 999999")
' "${reference_price}")"
  [[ "${tape_ready}" == "1" ]] && break
  sleep 1
done
[[ "${tape_ready}" == "1" ]] || die "Tape did not produce a positive recent tenant K-line within 60s"
log "Tape K-line ready: close=${tape_close}, volume=${tape_volume}, reference_deviation_bps=${tape_deviation_bps}."


log "Disabling Tape and waiting for the quote book to settle before user-hit tests."
mysql_exec -e "UPDATE dc_tenant_robot SET strategy_config=JSON_SET(strategy_config,'$.tape_enabled',CAST('false' AS JSON)),update_by='robot-e2e-tape-off',update_time=NOW() WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >/dev/null
stable_after_tape="0"
for _ in $(seq 1 90); do
  read -r runtime_status runtime_open_count <<<"$(mysql_exec -e "SELECT runtime_status,open_order_count FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc)"
  open_response="$(robot_open_orders 2>/dev/null || true)"
  read -r live_bids live_asks <<<"$(printf '%s' "${open_response}" | robot_open_value 'str(len({str(row.get("price")) for row in rows if str(row.get("side","")).lower()=="buy"}))+" "+str(len({str(row.get("price")) for row in rows if str(row.get("side","")).lower()=="sell"}))' 2>/dev/null || true)"
  [[ "${runtime_status}" == "RUNNING" && "${runtime_open_count}" == "20" && "${live_bids:-0}" == "10" && "${live_asks:-0}" == "10" ]] && stable_after_tape="1" || stable_after_tape="0"
  [[ "${stable_after_tape}" == "1" ]] && break
  sleep 1
done
[[ "${stable_after_tape}" == "1" ]] || die "Quote book did not return to stable 10+10 after Tape was disabled"
log "Quote book returned to stable 10+10 after Tape validation."


log "Hitting a Robot ask and verifying the partially filled level is replenished."
before_ids="$(robot_open_orders | robot_open_value '";".join(sorted(str(row.get("clordid")) for row in rows))')"
hit_ok="0"
hit_clid=""
for attempt in $(seq 1 20); do
  current_ask="$(robot_open_orders | robot_open_value 'min(float(row.get("price")) for row in rows if str(row.get("side","")).lower()=="sell")')"
  [[ -n "${current_ask}" && "${current_ask}" != "NULL" ]] || { sleep 1; continue; }
  hit_clid="ROBOT-HIT-${RUN_ID}-${attempt}"
  hit_response="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"key\":\"${LOCATION}\\u001f4\\u001fBTCUSDT\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${hit_clid}\",\"Terminal\":\"RobotE2E\",\"AlgoName\":\"robot-e2e-hit\",\"Side\":\"Buy\",\"Price\":\"${current_ask}\",\"UserID\":\"${TRADER_USER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"IOC\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${trader_token}" 2>/dev/null || true)"
  if [[ -z "${hit_response}" ]] || [[ "$(printf '%s' "${hit_response}" | json_eval 'd.get("code",-1)' 2>/dev/null || true)" != "0" ]]; then
    sleep 1
    continue
  fi
  for _ in $(seq 1 20); do
    trader_filled="$(mysql_exec -e "SELECT COUNT(*) FROM dc_orders WHERE location='${LOCATION}' AND clord_id='${hit_clid}' AND ord_status='Filled'" dc)"
    [[ "${trader_filled}" == "1" ]] && hit_ok="1" || hit_ok="0"
    [[ "${hit_ok}" == "1" ]] && break 2
    sleep 0.5
  done
done
[[ "${hit_ok}" == "1" ]] || die "User IOC did not hit a Robot ask after 20 live-book attempts"

replenished="0"
for _ in $(seq 1 60); do
  open_response="$(robot_open_orders 2>/dev/null || true)"
  open_count="$(printf '%s' "${open_response}" | robot_open_value 'len(rows)' 2>/dev/null || true)"
  current_ids="$(printf '%s' "${open_response}" | robot_open_value '";".join(sorted(str(row.get("clordid")) for row in rows))' 2>/dev/null || true)"
  [[ "${open_count}" == "20" && "${current_ids}" != "${before_ids}" ]] && replenished="1" || replenished="0"
  [[ "${replenished}" == "1" ]] && break
  sleep 1
done
[[ "${replenished}" == "1" ]] || die "Robot did not replenish all 20 quote levels after a user fill"
log "User hit and full 10+10 level replenishment passed (${hit_clid})."

read -r best_bid best_ask <<<"$(robot_open_orders | robot_open_value 'str(max(float(row.get("price")) for row in rows if str(row.get("side","")).lower()=="buy"))+" "+str(min(float(row.get("price")) for row in rows if str(row.get("side","")).lower()=="sell"))')"
tenant_tick_size="$(mysql_exec -e "SELECT tick_size FROM dc_tenant_symbol WHERE location='${LOCATION}' AND security_id='BTCUSDT' AND market_indicator='4' LIMIT 1" dc)"
inside_price="$(python3 - "${best_bid}" "${best_ask}" "${tenant_tick_size}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
bid,ask,tick=map(Decimal,sys.argv[1:])
assert tick > 0 and ask-bid >= tick*2
mid=(bid+ask)/2
price=(mid/tick).to_integral_value(rounding=ROUND_DOWN)*tick
if price <= bid: price=bid+tick
if price >= ask: price=ask-tick
assert bid < price < ask
print(price)
PY
)" || die "The live spread has no tenant-tick price inside it"

clid="ROBOT-SWEEP-${RUN_ID}"
place_response="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"key\":\"${LOCATION}\\u001f4\\u001fBTCUSDT\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"RobotE2E\",\"AlgoName\":\"robot-e2e-user\",\"Side\":\"Sell\",\"Price\":\"${inside_price}\",\"UserID\":\"${TRADER_USER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${trader_token}")"
expect_ok "place inside-spread user order" "${place_response}"

sweep_ok="0"
for _ in $(seq 1 60); do
  sweep_ok="$({
    cat <<SQL
SELECT IF(
  (SELECT ord_status FROM dc_orders WHERE location='${LOCATION}' AND clord_id='${clid}')='Filled'
  AND EXISTS (SELECT 1 FROM dc_orders_execorders e WHERE e.location='${LOCATION}'
              AND e.user_id='${TRADER_USER}' AND e.side='Sell'
              AND e.order_id=(SELECT o.order_id FROM dc_orders o WHERE o.location='${LOCATION}'
                              AND o.clord_id='${clid}')),
  1,0);
SQL
  } | mysql_exec dc)"
  [[ "${sweep_ok}" == "1" ]] && break
  sleep 1
done
[[ "${sweep_ok}" == "1" ]] || die "Robot did not consume the inside-spread user order"
robot_rows="$(mysql_exec -e "SELECT COUNT(*) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%'" dc)"
[[ "${robot_rows}" == "0" ]] || die "Internal Demo=1 Robot orders unexpectedly persisted (${robot_rows})"
log "User order was consumed by Robot IOC; user execution persisted and internal Demo=1 Robot orders stayed memory-only."

mysql_exec -e "UPDATE dc_tenant_robot SET enabled=0,update_by='robot-e2e',update_time=NOW() WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >/dev/null
stopped="0"
for _ in $(seq 1 60); do
  stopped="$({
    runtime_status="$(mysql_exec -e "SELECT runtime_status FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc)"
    open_count="$(robot_open_orders | robot_open_value 'len(rows)' 2>/dev/null || true)"
    [[ "${runtime_status}" == "STOPPED" && "${open_count}" == "0" ]] && printf 1 || printf 0
  })"
  [[ "${stopped}" == "1" ]] && break
  sleep 1
done
[[ "${stopped}" == "1" ]] || die "Disabling Robot did not cancel all live quotes"

summary="$(mysql_exec -e "SELECT CONCAT('persisted_robot_orders=',COUNT(*)) FROM dc_orders WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND clord_id LIKE '${robot_prefix}%'; SELECT CONCAT('trader_executions=',COUNT(*)) FROM dc_orders_execorders WHERE location='${LOCATION}' AND user_id='${TRADER_USER}'; SELECT CONCAT('foreign_location_orders=',COUNT(*)) FROM dc_orders WHERE location<>'${LOCATION}' AND clord_id LIKE '%${RUN_ID}%';" dc)"
grep -Fq 'foreign_location_orders=0' <<<"${summary}" || die "Robot E2E order identifiers leaked into another location"
log "PASS: ${summary//$'\n'/; }."
log "Evidence location retained: ${LOCATION}; hedge remained disabled because no external Binance credential was supplied."
