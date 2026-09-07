#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_LOCATION="${E2E_LOCATION:-WEB_E2E}"
E2E_USER="${E2E_USER:-webbuyer}"
RUN_ID="${E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"

log() { printf '[trading-settings-e2e] %s\n' "$*"; }
die() { printf '[trading-settings-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ "$(id -u)" -eq 0 ]] || die "Run with sudo"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"
safe_identifier "${E2E_LOCATION}" || die "Unsafe E2E_LOCATION"
safe_identifier "${E2E_USER}" || die "Unsafe E2E_USER"
safe_identifier "${RUN_ID}" || die "Unsafe E2E_RUN_ID"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BUYER="${E2E_USER}" \
E2E_SELLER="${E2E_USER}_peer" \
  "${SCRIPT_DIR}/prepare-web-trading-e2e.sh" >/dev/null

api_call() {
  local server="$1" method="$2" content="$3" token="${4:-}"
  local -a headers=(-H 'Content-Type: application/json')
  [[ -z "${token}" ]] || headers+=(-H "sessionId: ${token}")
  curl -fsS --max-time 30 "${headers[@]}" \
    --data "{\"serverName\":\"${server}\",\"method\":\"${method}\",\"content\":${content}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
}

json_value() {
  local expression="$1"
  shift
  python3 -c 'import json,sys; d=json.load(sys.stdin); value=eval(sys.argv[1],{"d":d,"sys":sys}); print(str(value).lower() if isinstance(value,bool) else value)' "${expression}" "$@"
}

expect_ok() {
  local label="$1" response="$2" code
  code="$(printf '%s' "${response}" | json_value 'd.get("code",-1)')"
  [[ "${code}" == "0" ]] || die "${label} failed: ${response}"
}

expect_rejected() {
  local label="$1" response="$2" code
  code="$(printf '%s' "${response}" | json_value 'd.get("code",-1)')"
  [[ "${code}" != "0" ]] || die "${label} unexpectedly succeeded: ${response}"
}

login_request="$(mktemp)"
printf '{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"%s","user_name":"%s","password":"%s","method":"login","client_type":"WEB","cid":"SETTINGS_%s","Location":"%s"}}\n' \
  "${E2E_USER}" "${E2E_USER}" "${E2E_PASSWORD}" "${RUN_ID}" "${E2E_LOCATION}" >"${login_request}"
login_response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' --data-binary "@${login_request}" \
  "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")"
rm -f "${login_request}"
token="$(printf '%s' "${login_response}" | json_value '(d.get("data") or {}).get("token",d.get("token",""))')"
[[ -n "${token}" ]] || die "Login returned no token"

funding_response="$(api_call TDSvr cashIn "{\"UserID\":\"${E2E_USER}\",\"Amount\":\"100000\",\"Location\":\"${E2E_LOCATION}\"}" "${token}")"
expect_ok "account funding" "${funding_response}"

config_response="$(api_call TradeSvr getSymbolConfig '{"SecurityID":"BTCUSDT"}' "${token}")"
expect_ok "initial configuration query" "${config_response}"
original_leverage="$(printf '%s' "${config_response}" | json_value 'd["data"]["leverage"]')"
original_position_type="$(printf '%s' "${config_response}" | json_value 'd["data"]["positionType"]')"
original_position_way="$(printf '%s' "${config_response}" | json_value 'd["data"]["positionWayType"]')"
max_leverage="$(printf '%s' "${config_response}" | json_value 'd["data"]["maxLeverage"]')"

target_leverage=5
(( max_leverage >= target_leverage )) || target_leverage="${max_leverage}"
[[ "${target_leverage}" != "${original_leverage}" ]] || target_leverage=4
(( target_leverage >= 1 && target_leverage <= max_leverage )) || target_leverage=1
target_position_type=Isolated
[[ "${original_position_type}" != Isolated ]] || target_position_type=Cross
target_position_way=0
[[ "${original_position_way}" != 0 ]] || target_position_way=1

restored=0
cleanup() {
  [[ "${restored}" == 1 ]] && return 0
  api_call OrderSvr cancelAllOrder "{\"SecurityID\":\"BTCUSDT\",\"MarketIndicator\":\"4\"}" "${token}" >/dev/null 2>&1 || true
  sleep 1
  api_call TradeSvr setAccountConfig "{\"PositionWayType\":\"${original_position_way}\"}" "${token}" >/dev/null 2>&1 || true
  api_call TradeSvr setPositionType "{\"SecurityID\":\"BTCUSDT\",\"PositionType\":\"${original_position_type}\"}" "${token}" >/dev/null 2>&1 || true
  api_call TradeSvr setLeverage "{\"SecurityID\":\"BTCUSDT\",\"Leverage\":${original_leverage}}" "${token}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

response="$(api_call TradeSvr setPositionType "{\"SecurityID\":\"BTCUSDT\",\"PositionType\":\"${target_position_type}\"}" "${token}")"
expect_ok "margin mode update" "${response}"
response="$(api_call TradeSvr setLeverage "{\"SecurityID\":\"BTCUSDT\",\"Leverage\":${target_leverage}}" "${token}")"
expect_ok "leverage update" "${response}"
response="$(api_call TradeSvr setAccountConfig "{\"PositionWayType\":\"${target_position_way}\"}" "${token}")"
expect_ok "position mode update" "${response}"

config_response="$(api_call TradeSvr getSymbolConfig '{"SecurityID":"BTCUSDT"}' "${token}")"
expect_ok "updated configuration query" "${config_response}"
actual="$(printf '%s' "${config_response}" | json_value 'str(d["data"]["leverage"])+"|"+str(d["data"]["positionType"])+"|"+str(d["data"]["positionWayType"])')"
[[ "${actual}" == "${target_leverage}|${target_position_type}|${target_position_way}" ]] ||
  die "Configuration did not round-trip: ${actual}"

market_response="$(api_call MDSvr queryPublicMarket "{\"SecurityID\":\"BTCUSDT\",\"location\":\"${E2E_LOCATION}\"}")"
expect_ok "public market query" "${market_response}"
best_bid="$(printf '%s' "${market_response}" | json_value 'max(float(x["MDEntryPx"]) for x in d["data"]["orderBook"]["NoMDEntries"] if str(x["MDEntryType"])=="0")')"
resting_price="$(python3 - "${best_bid}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
print((Decimal(sys.argv[1]) - Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_DOWN))
PY
)"
clord_id="SETTINGS-${RUN_ID}"
position_side_field=""
[[ "${target_position_way}" != 0 ]] || position_side_field=',"PositionSide":"Long"'
order_response="$(api_call OrderSvr placeOrder "{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clord_id}\",\"Terminal\":\"E2E\",\"AlgoName\":\"cross\",\"Side\":\"Buy\",\"Price\":\"${resting_price}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\"${position_side_field}}" "${token}")"
expect_ok "resting order placement" "${order_response}"

locked=false
for _ in $(seq 1 30); do
  open_orders_response="$(api_call OrderSvr queryOpenOrder '{"securityid":"BTCUSDT"}' "${token}")"
  expect_ok "active order query" "${open_orders_response}"
  active_order_count="$(printf '%s' "${open_orders_response}" | json_value 'sum(1 for x in (d.get("data") or []) if x.get("ClOrdID")==sys.argv[2])' "${clord_id}")"
  config_response="$(api_call TradeSvr getSymbolConfig '{"SecurityID":"BTCUSDT"}' "${token}")"
  if [[ "${active_order_count}" == "1" ]] && \
     [[ "$(printf '%s' "${config_response}" | json_value 'd["data"]["hasOpenOrders"]')" == true ]]; then
    locked=true
    break
  fi
  sleep 0.2
done
[[ "${locked}" == true ]] || die "TradeSvr did not observe the active order"
[[ "$(printf '%s' "${config_response}" | json_value 'd["data"]["leverageChangeAllowed"]')" == false ]] || die "Leverage remained editable with an open order"
[[ "$(printf '%s' "${config_response}" | json_value 'd["data"]["positionTypeChangeAllowed"]')" == false ]] || die "Margin mode remained editable with an open order"
[[ "$(printf '%s' "${config_response}" | json_value 'd["data"]["positionWayTypeChangeAllowed"]')" == false ]] || die "Position mode remained editable with an open order"

next_leverage=$(( target_leverage == 1 ? 2 : 1 ))
response="$(api_call TradeSvr setLeverage "{\"SecurityID\":\"BTCUSDT\",\"Leverage\":${next_leverage}}" "${token}")"
expect_rejected "leverage update while order is active" "${response}"
response="$(api_call TradeSvr setAccountConfig "{\"PositionWayType\":\"${original_position_way}\"}" "${token}")"
expect_rejected "position mode update while order is active" "${response}"

response="$(api_call OrderSvr cancelAllOrder '{"SecurityID":"BTCUSDT","MarketIndicator":"4","AlgoName":"cross"}' "${token}")"
expect_ok "cancel all" "${response}"
for _ in $(seq 1 30); do
  config_response="$(api_call TradeSvr getSymbolConfig '{"SecurityID":"BTCUSDT"}' "${token}")"
  [[ "$(printf '%s' "${config_response}" | json_value 'd["data"]["hasOpenOrders"]')" == false ]] && break
  sleep 0.2
done
[[ "$(printf '%s' "${config_response}" | json_value 'd["data"]["hasOpenOrders"]')" == false ]] || die "Active-order lock did not clear after cancellation"

response="$(api_call TradeSvr setAccountConfig "{\"PositionWayType\":\"${original_position_way}\"}" "${token}")"; expect_ok "restore position mode" "${response}"
response="$(api_call TradeSvr setPositionType "{\"SecurityID\":\"BTCUSDT\",\"PositionType\":\"${original_position_type}\"}" "${token}")"; expect_ok "restore margin mode" "${response}"
response="$(api_call TradeSvr setLeverage "{\"SecurityID\":\"BTCUSDT\",\"Leverage\":${original_leverage}}" "${token}")"; expect_ok "restore leverage" "${response}"
restored=1

log "PASS location=${E2E_LOCATION} user=${E2E_USER} leverage=${target_leverage} margin=${target_position_type} positionMode=${target_position_way} activeOrderLock=true restored=true"
