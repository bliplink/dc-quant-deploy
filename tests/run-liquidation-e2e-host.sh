#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
RUN_ID="${LIQ_E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
LIQ_LOCATION="${LIQ_E2E_LOCATION:-LIQ_E2E_${RUN_ID}}"
OTHER_LOCATION="${LIQ_E2E_OTHER_LOCATION:-${LIQ_LOCATION}_FOREIGN}"
LIQ_USER="${LIQ_E2E_USER:-liq_trigger_${RUN_ID}}"
OPEN_USER="${LIQ_E2E_OPEN_USER:-liq_open_${RUN_ID}}"
MAKER_USER="${LIQ_E2E_MAKER:-liq_maker_${RUN_ID}}"
liq_test_stopped="false"
override_installed="false"
override_session=""

log() { printf '[liq-e2e] %s\n' "$*"; }
die() { printf '[liq-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
for value in "${RUN_ID}" "${LIQ_LOCATION}" "${OTHER_LOCATION}" "${LIQ_USER}" "${OPEN_USER}" "${MAKER_USER}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LIQ_LOCATION}" != "${OTHER_LOCATION}" ]] || die "Liquidation locations must differ"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
E2E_PASSWORD="${E2E_PASSWORD:-${LOGIN_DEFAULT_PASSWORD:-}}"
[[ -n "${E2E_PASSWORD}" ]] || die "E2E_PASSWORD or LOGIN_DEFAULT_PASSWORD is required"

# shellcheck source=restart-order-trade-e2e.sh
. "${SCRIPT_DIR}/restart-order-trade-e2e.sh"

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

clear_mark_override_best_effort() {
  [[ "${override_installed}" == "true" && -n "${override_session}" ]] || return 0
  curl -fsS --max-time 10 -H 'Content-Type: application/json' -H "sessionId: ${override_session}" \
    --data "{\"serverName\":\"MDSvr\",\"method\":\"e2eMarkPriceOverride\",\"key\":\"${LIQ_LOCATION}\\u001f4\\u001fBTCUSDT\",\"content\":{\"action\":\"CLEAR\",\"token\":\"${MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN}\",\"location\":\"${LIQ_LOCATION}\",\"securityID\":\"BTCUSDT\"}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" >/dev/null 2>&1 || true
  override_installed="false"
}

cleanup() {
  clear_mark_override_best_effort
  if [[ "${liq_test_stopped}" == "true" ]]; then
    docker start dc-saas-liqsvr >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

query_mark_price() {
  local response
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data "{\"serverName\":\"MDSvr\",\"method\":\"queryPublicMarket\",\"key\":\"${LIQ_LOCATION}\\u001f4\\u001fBTCUSDT\",\"content\":{\"securityID\":\"BTCUSDT\",\"location\":\"${LIQ_LOCATION}\"}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
    die "Could not query the current tenant MarkPrice"
  printf '%s' "${response}" | python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin)
value=Decimal(str(d["data"]["ticker"]["MarkPrice"]))
assert value > 0
print(value)
' || die "MDSvr returned no positive tenant MarkPrice: ${response}"
}

password_hash="$(printf '%s' "${E2E_PASSWORD}" | sha256sum | awk '{print $1}')"

login_user() {
  local user="$1" request response token start
  request="$(mktemp)"
  chmod 0600 "${request}"
  printf '{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"%s","user_name":"%s","password":"%s","method":"login","client_type":"WEB","cid":"LIQ_E2E_%s","Location":"%s"}}\n' \
    "${user}" "${user}" "${E2E_PASSWORD}" "${user}" "${LIQ_LOCATION}" >"${request}"
  start="$(date +%s)"
  while true; do
    response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
      --data-binary "@${request}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' <<<"${response}")"
    if [[ -n "${token}" ]]; then
      rm -f "${request}"
      printf '%s' "${token}"
      return 0
    fi
    if (( $(date +%s) - start >= 120 )); then
      rm -f "${request}"
      die "Login returned no session token for ${user}: ${response}"
    fi
    sleep 2
  done
}

fund_trade_account() {
  local user="$1" token="$2" target_balance="${3:-100000}" response current_balance top_up code
  # This helper mutates the clustered Trade state through its public API only.
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${token}" \
    --data "{\"serverName\":\"TradeSvr\",\"method\":\"cashOut\",\"key\":\"${LIQ_LOCATION}\",\"content\":{\"Amount\":\"0\",\"UserID\":\"${user}\",\"Location\":\"${LIQ_LOCATION}\",\"Demo\":\"1\"}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
    die "Could not initialize TradeSvr account state for ${user}"
  IFS=$'\t' read -r code current_balance < <(printf '%s' "${response}" | python3 -c 'import json,sys
d=json.load(sys.stdin); x=d.get("data") or {}
print("{}\t{}".format(d.get("code",-1),x.get("Balance",x.get("balance",0))))')
  [[ "${code}" == "0" ]] || die "TradeSvr cashOut(0) rejected for ${user}: ${response}"
  top_up="$(python3 - "${target_balance}" "${current_balance}" <<'PY'
from decimal import Decimal
import sys
target,current=map(Decimal,sys.argv[1:3])
delta=target-current
print(format(delta if delta > 0 else Decimal(0),'f'))
PY
)"
  if [[ "${top_up}" != "0" ]]; then
    response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${token}" \
      --data "{\"serverName\":\"TradeSvr\",\"method\":\"cashIn\",\"key\":\"${LIQ_LOCATION}\",\"content\":{\"Amount\":\"${top_up}\",\"UserID\":\"${user}\",\"Location\":\"${LIQ_LOCATION}\",\"Demo\":\"1\"}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
      die "Could not fund TradeSvr account state for ${user}"
    grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}" ||
      die "TradeSvr cashIn rejected for ${user}: ${response}"
  fi
  log "TradeSvr hot account initialized for ${user}; top_up=${top_up}"
}

api_call() {
  local server="$1" method="$2" content="$3" token="${4:-}" key="${5:-${LIQ_LOCATION}}"
  local -a headers=(-H 'Content-Type: application/json')
  [[ -z "${token}" ]] || headers+=(-H "sessionId: ${token}")
  curl -fsS --max-time 30 "${headers[@]}" \
    --data "{\"serverName\":\"${server}\",\"method\":\"${method}\",\"key\":\"${key}\",\"content\":${content}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
}

expect_ok() {
  local label="$1" response="$2" code
  code="$(printf '%s' "${response}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("code",-1))')"
  [[ "${code}" == "0" ]] || die "${label} failed: ${response}"
}

set_leverage_100() {
  local token="$1" response
  response="$(api_call TradeSvr setLeverage '{"SecurityID":"BTCUSDT","Leverage":100}' "${token}")" ||
    die "Could not set leverage"
  expect_ok "set leverage=100" "${response}"
}

place_order() {
  local user="$1" token="$2" side="$3" qty="$4" price="$5" tif="$6" clid="$7"
  local response key="${LIQ_LOCATION}\\u001f4\\u001fBTCUSDT"
  response="$(api_call OrderSvr placeOrder "{\"OCType\":\"OPEN\",\"OrderQty\":\"${qty}\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"${side}\",\"Price\":\"${price}\",\"UserID\":\"${user}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"${tif}\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"false\",\"Location\":\"${LIQ_LOCATION}\",\"Demo\":\"1\"}" "${token}" "${key}")" ||
    die "Could not place ${clid}"
  expect_ok "place ${clid}" "${response}"
}

wait_order_status() {
  local clid="$1" status="$2" count=0
  for _ in $(seq 1 80); do
    count="$(mysql_exec -e "SELECT COUNT(*) FROM dc.dc_order_projection_event WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.location'))='${LIQ_LOCATION}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.clOrderId'))='${clid}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='${status}';" dc)"
    [[ "${count}" -ge 1 ]] && return 0
    sleep 0.5
  done
  die "Order ${clid} did not reach ${status} in the authoritative Order projection journal"
}

query_trade_position() {
  local token="$1"
  api_call TradeSvr queryTradePosition "{\"userid\":\"${LIQ_USER}\",\"location\":\"${LIQ_LOCATION}\",\"securityid\":\"BTCUSDT\"}" "${token}"
}

query_account_state() {
  local token="$1"
  api_call TradeSvr cashOut "{\"Amount\":\"0\",\"UserID\":\"${LIQ_USER}\",\"Location\":\"${LIQ_LOCATION}\",\"Demo\":\"1\"}" "${token}"
}

install_mark_override() {
  local mark="$1" response key="${LIQ_LOCATION}\\u001f4\\u001fBTCUSDT"
  [[ -n "${override_session}" ]] || die "Authenticated liquidation session is required for tenant MarkPrice override"
  response="$(api_call MDSvr e2eMarkPriceOverride "{\"action\":\"SET\",\"token\":\"${MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN}\",\"location\":\"${LIQ_LOCATION}\",\"securityID\":\"BTCUSDT\",\"markPrice\":\"${mark}\",\"indexPrice\":\"${mark}\",\"fundingRate\":\"0\",\"ttlMs\":${MDSVR_E2E_MARK_PRICE_OVERRIDE_MAX_TTL_MS:-60000}}" "${override_session}" "${key}")" ||
    die "Could not install tenant MarkPrice override"
  expect_ok "install tenant MarkPrice override" "${response}"
  override_installed="true"
}

wait_for_port() {
  local port="$1" service="$2" start
  start="$(date +%s)"
  until python3 - "${port}" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
sock.settimeout(1)
try:
    status = sock.connect_ex(("127.0.0.1", int(sys.argv[1])))
finally:
    sock.close()
raise SystemExit(0 if status == 0 else 1)
PY
  do
    if (( $(date +%s) - start >= 120 )); then
      docker logs --tail 120 "${service}" >&2 || true
      die "${service} did not listen on ${port}"
    fi
    sleep 2
  done
}

wait_for_route() {
  local server="$1" start response content='{}' key=''
  start="$(date +%s)"
  if [[ "${server}" == "OrderSvr" ]]; then
    content="{\"Location\":\"${LIQ_LOCATION}\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\"}"
    key=",\"key\":\"${LIQ_LOCATION}\\u001f4\\u001fBTCUSDT\""
  fi
  while true; do
    response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
      --data "{\"serverName\":\"${server}\",\"method\":\"__e2e_readiness__\"${key},\"content\":${content}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" ]] &&
       ! grep -Eq 'is not Online|PARTITION_NOT_READY|STALE_PARTITION' <<<"${response}"; then return 0; fi
    if (( $(date +%s) - start >= 120 )); then die "${server} did not become routable"; fi
    sleep 2
  done
}

[[ "${MDSVR_E2E_MARK_PRICE_OVERRIDE_ENABLED:-false}" == "true" ]] ||
  die "MDSVR_E2E_MARK_PRICE_OVERRIDE_ENABLED=true is required for deterministic liquidation acceptance"
[[ -n "${MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN:-}" ]] ||
  die "MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN is required"
[[ "${MDSVR_E2E_MARK_PRICE_OVERRIDE_MAX_TTL_MS:-60000}" =~ ^[1-9][0-9]*$ ]] ||
  die "MDSVR_E2E_MARK_PRICE_OVERRIDE_MAX_TTL_MS must be a positive integer"

log "Stopping LiqSvr while a real authoritative position is created in ${LIQ_LOCATION}."
docker stop dc-saas-liqsvr >/dev/null
liq_test_stopped="true"

log "Provisioning isolated LoginSvr identities only; Order/Trade state will be created exclusively through service APIs."
mysql_exec dc <<SQL
INSERT INTO dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${LIQ_USER}','${LIQ_USER}','Liquidation Trigger','${password_hash}','1','1',NOW(),NOW(),'1','1','1','LIQ_E2E','${LIQ_LOCATION}'),
  ('${OPEN_USER}','${OPEN_USER}','Liquidation Opening Peer','${password_hash}','1','1',NOW(),NOW(),'1','1','1','LIQ_E2E','${LIQ_LOCATION}'),
  ('${MAKER_USER}','${MAKER_USER}','Liquidation Maker','${password_hash}','1','1',NOW(),NOW(),'1','1','1','LIQ_E2E','${LIQ_LOCATION}')
ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',enable_trade='1',enable_cash_in='1',enable_cash_out='1',location=VALUES(location),update_time=NOW();
SQL

docker restart dc-saas-loginsvr >/dev/null
wait_for_port "${LOGINSVR_GW_PORT}" dc-saas-loginsvr
wait_for_route OrderSvr
wait_for_route TradeSvr

liq_session="$(login_user "${LIQ_USER}")"
override_session="${liq_session}"
open_session="$(login_user "${OPEN_USER}")"
maker_session="$(login_user "${MAKER_USER}")"
fund_trade_account "${LIQ_USER}" "${liq_session}" 100
fund_trade_account "${OPEN_USER}" "${open_session}" 100000
fund_trade_account "${MAKER_USER}" "${maker_session}" 100000
set_leverage_100 "${liq_session}"
set_leverage_100 "${open_session}"
set_leverage_100 "${maker_session}"

fixture_mark="$(query_mark_price)"
entry_price="$(python3 - "${fixture_mark}" <<'PY'
from decimal import Decimal, ROUND_HALF_UP
import sys
print(Decimal(sys.argv[1]).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
PY
)"
open_clid="LIQ-OPEN-${RUN_ID}"
trigger_clid="LIQ-TRIGGER-${RUN_ID}"
maker_clid="LIQ-MAKER-${RUN_ID}"

log "Creating real 0.004 BTC long through OrderSvr/TradeSvr at ${entry_price}."
place_order "${OPEN_USER}" "${open_session}" Sell 0.004 "${entry_price}" GTC "${open_clid}"
wait_order_status "${open_clid}" New
place_order "${LIQ_USER}" "${liq_session}" Buy 0.004 "${entry_price}" IOC "${trigger_clid}"
wait_order_status "${trigger_clid}" Filled
wait_order_status "${open_clid}" Filled

position_response=""
for _ in $(seq 1 60); do
  position_response="$(query_trade_position "${liq_session}" 2>/dev/null || true)"
  if printf '%s' "${position_response}" | python3 -c '
import json,sys
from decimal import Decimal
try:
 d=json.load(sys.stdin); p=d.get("data") or {}
 ok=d.get("code")==0 and Decimal(str(p.get("LongPosition",p.get("longPosition",0))))==Decimal("0.004")
except Exception: ok=False
raise SystemExit(0 if ok else 1)
'; then break; fi
  sleep 0.5
done
printf '%s' "${position_response}" | python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin); p=d.get("data") or {}
assert d.get("code")==0 and Decimal(str(p.get("LongPosition",p.get("longPosition",0))))==Decimal("0.004"), d
' || die "TradeSvr never exposed the authoritative 0.004 BTC long: ${position_response}"

log "Withdrawing only available collateral through TradeSvr, leaving a small safety reserve before the controlled Mark move."
account_response="$(query_account_state "${liq_session}")"
expect_ok "query hot account through cashOut(0)" "${account_response}"
current_mark="$(query_mark_price)"
withdraw_amount="$(python3 - "${account_response}" "${position_response}" "${current_mark}" <<'PY'
import json,sys
from decimal import Decimal
account=(json.loads(sys.argv[1]).get('data') or {})
pos=(json.loads(sys.argv[2]).get('data') or {})
mark=Decimal(sys.argv[3])
balance=Decimal(str(account.get('Balance',account.get('balance',0))))
used=Decimal(str(account.get('UsedMargin',account.get('usedMargin',0))))
frozen=Decimal(str(account.get('FreezedMargin',account.get('freezedMargin',0))))
commission=Decimal(str(account.get('FreezedCommission',account.get('freezedCommission',0))))
qty=Decimal(str(pos.get('LongPosition',pos.get('longPosition',0))))
avg=Decimal(str(pos.get('LongAverage',pos.get('longAverage',0))))
pnl=qty*(mark-avg)
available=balance-used-frozen-commission+min(pnl,Decimal(0))
reserve=Decimal('2')
amount=max(Decimal(0),available-reserve)
print(amount.quantize(Decimal('0.00000001')))
PY
)"
[[ "${withdraw_amount}" != "0E-8" && "${withdraw_amount}" != "0.00000000" ]] ||
  die "No withdrawable collateral remained for deterministic liquidation setup"
withdraw_response="$(api_call TradeSvr cashOut "{\"Amount\":\"${withdraw_amount}\",\"UserID\":\"${LIQ_USER}\",\"Location\":\"${LIQ_LOCATION}\",\"Demo\":\"1\"}" "${liq_session}")"
expect_ok "cashOut available collateral" "${withdraw_response}"

log "Waiting for TradeSvr to publish authoritative VALID risk after the collateral change."
risk_row=""
for _ in $(seq 1 80); do
  position_response="$(query_trade_position "${liq_session}" 2>/dev/null || true)"
  risk_row="$(printf '%s' "${position_response}" | python3 -c '
import json,sys
from decimal import Decimal
try:
 d=json.load(sys.stdin); p=d.get("data") or {}
 qty=Decimal(str(p.get("LongPosition",p.get("longPosition",0))))
 liq=Decimal(str(p.get("LongLiqPrice",p.get("longLiqPrice",0))))
 bank=Decimal(str(p.get("LongBankruptcyPrice",p.get("longBankruptcyPrice",0))))
 status=str(p.get("PositionStatus",p.get("positionStatus","")))
 print(f"{qty}\t{liq}\t{bank}\t{status}")
except Exception:
 print("0\t0\t0\t")
' 2>/dev/null || true)"
  IFS=$'\t' read -r auth_qty current_liq bankruptcy position_status <<<"${risk_row}"
  if [[ "${auth_qty}" == "0.004" && "${position_status}" == "1" ]] &&
     python3 - "${current_liq}" "${bankruptcy}" <<'PY' >/dev/null 2>&1
from decimal import Decimal
import sys
raise SystemExit(0 if Decimal(sys.argv[1]) > 0 and Decimal(sys.argv[2]) > 0 else 1)
PY
  then break; fi
  sleep 0.5
done
[[ "${auth_qty:-}" == "0.004" && "${position_status:-}" == "1" ]] ||
  die "TradeSvr did not publish authoritative liquidation risk fields: ${position_response}"

injected_mark="$(python3 - "${current_liq}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
liq=Decimal(sys.argv[1])
value=(liq*Decimal('0.998')).quantize(Decimal('0.1'), rounding=ROUND_DOWN)
if value >= liq: value=(liq-Decimal('0.1')).quantize(Decimal('0.1'), rounding=ROUND_DOWN)
assert value > 0
print(value)
PY
)"

log "Resting 0.001 BTC bid for the partial-liquidation Market/IOC fill."
place_order "${MAKER_USER}" "${maker_session}" Buy 0.001 "${entry_price}" GTC "${maker_clid}"
wait_order_status "${maker_clid}" New

foreign_mark_before="$(LIQ_LOCATION="${OTHER_LOCATION}" query_mark_price)"
current_mark="$(query_mark_price)"
python3 - "${current_mark}" "${current_liq}" <<'PY' >/dev/null ||
from decimal import Decimal
import sys
mark,liq=map(Decimal,sys.argv[1:3])
assert mark > liq
PY
  die "Position became unsafe before controlled MarkPrice injection: mark=${current_mark} liq=${current_liq}"

log "Starting LiqSvr under the safe live MarkPrice, then waiting for its gateway plus authoritative Order/Trade routes."
docker start dc-saas-liqsvr >/dev/null
liq_test_stopped="false"
wait_for_port "${LIQSVR_GW_PORT}" dc-saas-liqsvr
wait_for_route OrderSvr
wait_for_route TradeSvr
for _ in $(seq 1 40); do
  current_mark="$(query_mark_price 2>/dev/null || true)"
  [[ -n "${current_mark}" ]] && break
  sleep 0.25
done
[[ -n "${current_mark:-}" ]] || die "MDSvr tenant MarkPrice did not become readable after LiqSvr start"
sleep 2

log "Installing tenant-only MarkPrice override ${LIQ_LOCATION}/BTCUSDT=${injected_mark}; foreign tenant remains on live APS mark."
install_mark_override "${injected_mark}"

for _ in $(seq 1 40); do
  current_mark="$(query_mark_price 2>/dev/null || true)"
  [[ "${current_mark}" == "${injected_mark}" ]] && break
  sleep 0.25
done
[[ "${current_mark}" == "${injected_mark}" ]] ||
  die "Target tenant did not receive injected MarkPrice: expected=${injected_mark} actual=${current_mark}"
foreign_mark_after="$(LIQ_LOCATION="${OTHER_LOCATION}" query_mark_price)"
[[ "${foreign_mark_after}" != "${injected_mark}" ]] ||
  die "Tenant-scoped MarkPrice override leaked into ${OTHER_LOCATION}"

log "Tenant MarkPrice override is active and isolated; TradeSvr must now expose the same position as unsafe before LiqSvr is judged by the resulting liquidation fill."

position_response=""
for _ in $(seq 1 80); do
  position_response="$(query_trade_position "${liq_session}" 2>/dev/null || true)"
  if printf '%s' "${position_response}" | python3 -c '
import json,sys
from decimal import Decimal
try:
 d=json.load(sys.stdin); p=d.get("data") or {}
 qty=Decimal(str(p.get("LongPosition",p.get("longPosition",0))))
 liq=Decimal(str(p.get("LongLiqPrice",p.get("longLiqPrice",0))))
 status=str(p.get("PositionStatus",p.get("positionStatus","")))
 mark=Decimal(sys.argv[1])
 ok=d.get("code")==0 and status=="1" and qty==Decimal("0.004") and liq>0 and mark<=liq
except Exception: ok=False
raise SystemExit(0 if ok else 1)
' "${injected_mark}"; then break; fi
  sleep 0.25
done
printf '%s' "${position_response}" | python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin); p=d.get("data") or {}; mark=Decimal(sys.argv[1])
assert str(p.get("PositionStatus",p.get("positionStatus","")))=="1"
assert Decimal(str(p.get("LongPosition",p.get("longPosition",0))))==Decimal("0.004")
assert mark <= Decimal(str(p.get("LongLiqPrice",p.get("longLiqPrice",0))))
' "${injected_mark}" || die "Controlled tenant MarkPrice did not create an authoritative unsafe position: ${position_response}"

liquidation_count="0"
for _ in $(seq 1 450); do
  liquidation_count="$(mysql_exec -e "SELECT COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderId'))) FROM dc.dc_order_projection_event WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.location'))='${LIQ_LOCATION}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.userId'))='${LIQ_USER}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.securityId'))='BTCUSDT' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.closeBy'))='liq_partial' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='Filled' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderType'))='Market' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.timeInForce'))='IOC' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.reduceOnly'))='true';" dc)"
  if [[ "${liquidation_count}" -ge 1 ]]; then
    clear_mark_override_best_effort
    break
  fi
  sleep 0.2
done
if [[ "${liquidation_count}" -lt 1 ]]; then
  docker logs --tail 220 dc-saas-liqsvr >&2 || true
  die "LiqSvr did not create a filled reduce-only Market/IOC partial-liquidation event"
fi
sleep 2
liquidation_count="$(mysql_exec -e "SELECT COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderId'))) FROM dc.dc_order_projection_event WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.location'))='${LIQ_LOCATION}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.userId'))='${LIQ_USER}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.securityId'))='BTCUSDT' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.closeBy'))='liq_partial' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='Filled';" dc)"
[[ "${liquidation_count}" == "1" ]] || die "Expected exactly one partial-liquidation fill in the Order projection journal, found ${liquidation_count}"

liq_clid="$(mysql_exec -e "SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.clOrderId')) FROM dc.dc_order_projection_event WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.location'))='${LIQ_LOCATION}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.userId'))='${LIQ_USER}' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.closeBy'))='liq_partial' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='Filled' ORDER BY create_time DESC,journal_seq DESC LIMIT 1;" dc)"
[[ -n "${liq_clid}" ]] || die "Could not resolve the partial-liquidation ClOrdID from the Order projection journal"

verification="$({
  cat <<SQL
SELECT p.long_position,p.long_used_margin,b.used_margin,b.balance
FROM dc.dc_orders_position p
JOIN dc.dc_users_balance b ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LIQ_LOCATION}' AND p.user_id='${LIQ_USER}' AND p.security_id='BTCUSDT';
SELECT
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.execution.qty')),
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.execution.price')),
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.execution.fee')),
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.execution.realizedPnl'))
FROM dc.dc_order_projection_event
WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.clOrderId'))='${liq_clid}'
  AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='Filled'
ORDER BY create_time DESC,journal_seq DESC LIMIT 1;
SELECT
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus')),
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.cumQty')),
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.unOpenQty'))
FROM dc.dc_order_projection_event
WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.clOrderId'))='${maker_clid}'
  AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='Filled'
ORDER BY create_time DESC,journal_seq DESC LIMIT 1;
SQL
} | mysql_exec dc)"
rows=()
while IFS= read -r line; do rows[${#rows[@]}]="$line"; done <<<"${verification}"
[[ "${#rows[@]}" -eq 3 ]] || die "Unexpected liquidation verification output: ${verification}"
if ! python3 - "${rows[0]}" "${rows[1]}" "${rows[2]}" <<'PY'
from decimal import Decimal
import sys
position, execution, maker = (row.split('\t') for row in sys.argv[1:4])
qty, position_margin, account_margin, balance = map(Decimal, position)
last_qty, last_px, fee, realized = map(Decimal, execution)
maker_status, maker_cum, maker_leaves = maker
epsilon=Decimal('0.00000001')
assert qty == Decimal('0.003')
assert position_margin > 0 and account_margin > 0
assert abs(position_margin-account_margin) <= epsilon
assert balance.is_finite()
assert last_qty == Decimal('0.001')
assert last_px > 0
assert fee <= 0
assert realized.is_finite()
assert maker_status == 'Filled'
assert Decimal(maker_cum) == Decimal('0.001')
assert Decimal(maker_leaves) == 0
PY
then
  die "Partial liquidation accounting mismatch: ${verification}"
fi

final_position="$(query_trade_position "${liq_session}")"
printf '%s' "${final_position}" | python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin); p=d.get("data") or {}
assert d.get("code")==0
assert Decimal(str(p.get("LongPosition",p.get("longPosition",0))))==Decimal("0.003")
' || die "Authoritative TradeSvr position did not converge to 0.003 after partial liquidation: ${final_position}"

log "PASS: authoritative Demo=1 0.004 BTC position -> tenant-only unsafe MarkPrice -> exactly one live reduce-only Market/IOC partial liquidation recorded in the Order projection journal; foreign tenant MarkPrice remained isolated (${foreign_mark_before} -> ${foreign_mark_after})."
