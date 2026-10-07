#!/usr/bin/env bash
# Shared authoritative helpers for liquidation/final-liquidation/ADL acceptance.
# The caller must source its ENV_FILE before sourcing this file.

e2e_mysql() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

e2e_api_call() {
  local server="$1" method="$2" key="$3" content="$4" token="${5:-}"
  local -a headers=(-H 'Content-Type: application/json')
  [[ -z "${token}" ]] || headers+=(-H "sessionId: ${token}")
  curl -fsS --max-time 30 "${headers[@]}" \
    --data "{\"serverName\":\"${server}\",\"method\":\"${method}\",\"key\":\"${key}\",\"content\":${content}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
}

e2e_expect_ok() {
  local label="$1" response="$2" code
  code="$(printf '%s' "${response}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("code",-1))')"
  [[ "${code}" == "0" ]] || {
    printf '[liquidation-e2e-common] ERROR: %s failed: %s\n' "${label}" "${response}" >&2
    return 1
  }
}

e2e_login_user() {
  local user="$1" location="$2" cid_prefix="$3" password="$4"
  local request response token start
  request="$(mktemp)"
  chmod 0600 "${request}"
  printf '{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"%s","user_name":"%s","password":"%s","method":"login","client_type":"WEB","cid":"%s_%s","Location":"%s"}}\n' \
    "${user}" "${user}" "${password}" "${cid_prefix}" "${user}" "${location}" >"${request}"
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
      printf '[liquidation-e2e-common] ERROR: login returned no token for %s@%s: %s\n' \
        "${user}" "${location}" "${response}" >&2
      return 1
    fi
    sleep 2
  done
}

e2e_fund_trade_account() {
  local user="$1" token="$2" location="$3" target_balance="$4"
  local response code current_balance top_up
  response="$(e2e_api_call TradeSvr cashOut "${location}" \
    "{\"Amount\":\"0\",\"UserID\":\"${user}\",\"Location\":\"${location}\",\"Demo\":\"1\"}" "${token}")" || return 1
  IFS=$'\t' read -r code current_balance < <(printf '%s' "${response}" | python3 -c '
import json,sys
d=json.load(sys.stdin); x=d.get("data") or {}
print("{}\t{}".format(d.get("code",-1),x.get("Balance",x.get("balance",0))))
')
  [[ "${code}" == "0" ]] || return 1
  top_up="$(python3 - "${target_balance}" "${current_balance}" <<'PY'
from decimal import Decimal
import sys
target,current=map(Decimal,sys.argv[1:3])
delta=target-current
print(format(delta if delta > 0 else Decimal(0),'f'))
PY
)"
  if [[ "${top_up}" != "0" ]]; then
    response="$(e2e_api_call TradeSvr cashIn "${location}" \
      "{\"Amount\":\"${top_up}\",\"UserID\":\"${user}\",\"Location\":\"${location}\",\"Demo\":\"1\"}" "${token}")" || return 1
    e2e_expect_ok "cashIn ${user}@${location}" "${response}" || return 1
  fi
}

e2e_set_leverage_100() {
  local token="$1" location="$2" response
  response="$(e2e_api_call TradeSvr setLeverage "${location}" \
    '{"SecurityID":"BTCUSDT","Leverage":100}' "${token}")" || return 1
  e2e_expect_ok "setLeverage ${location}" "${response}"
}

e2e_place_open_order() {
  local location="$1" user="$2" token="$3" side="$4" qty="$5" price="$6" tif="$7" clid="$8"
  local key response
  key="${location}\\u001f4\\u001fBTCUSDT"
  response="$(e2e_api_call OrderSvr placeOrder "${key}" \
    "{\"OCType\":\"OPEN\",\"OrderQty\":\"${qty}\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"${side}\",\"Price\":\"${price}\",\"UserID\":\"${user}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"${tif}\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"false\",\"Location\":\"${location}\",\"Demo\":\"1\"}" \
    "${token}")" || return 1
  e2e_expect_ok "place ${clid}" "${response}"
}

e2e_wait_order_status() {
  local location="$1" clid="$2" status="$3" count
  for _ in $(seq 1 100); do
    count="$(e2e_mysql -e "SELECT COUNT(*) FROM dc.dc_order_projection_event
      WHERE JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.location'))='${location}'
        AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.clOrderId'))='${clid}'
        AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.order.orderStatus'))='${status}';" dc)"
    [[ "${count}" -ge 1 ]] && return 0
    sleep 0.5
  done
  return 1
}

e2e_query_position() {
  local location="$1" user="$2" token="$3"
  e2e_api_call TradeSvr queryTradePosition "${location}" \
    "{\"userid\":\"${user}\",\"location\":\"${location}\",\"securityid\":\"BTCUSDT\"}" "${token}"
}

e2e_query_account() {
  local location="$1" user="$2" token="$3"
  e2e_api_call TradeSvr cashOut "${location}" \
    "{\"Amount\":\"0\",\"UserID\":\"${user}\",\"Location\":\"${location}\",\"Demo\":\"1\"}" "${token}"
}

e2e_cash_out() {
  local location="$1" user="$2" token="$3" amount="$4" response
  response="$(e2e_api_call TradeSvr cashOut "${location}" \
    "{\"Amount\":\"${amount}\",\"UserID\":\"${user}\",\"Location\":\"${location}\",\"Demo\":\"1\"}" "${token}")" || return 1
  e2e_expect_ok "cashOut ${user}@${location}" "${response}"
}

e2e_query_mark() {
  local location="$1" response
  response="$(e2e_api_call MDSvr queryPublicMarket "${location}\\u001f4\\u001fBTCUSDT" \
    "{\"securityID\":\"BTCUSDT\",\"location\":\"${location}\"}")" || return 1
  printf '%s' "${response}" | python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin); value=Decimal(str(d["data"]["ticker"]["MarkPrice"]))
assert value > 0
print(value)
'
}

e2e_set_mark_override() {
  local location="$1" session="$2" mark="$3" response
  response="$(e2e_api_call MDSvr e2eMarkPriceOverride "${location}\\u001f4\\u001fBTCUSDT" \
    "{\"action\":\"SET\",\"token\":\"${MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN}\",\"location\":\"${location}\",\"securityID\":\"BTCUSDT\",\"markPrice\":\"${mark}\",\"indexPrice\":\"${mark}\",\"fundingRate\":\"0\",\"ttlMs\":${MDSVR_E2E_MARK_PRICE_OVERRIDE_MAX_TTL_MS:-60000}}" \
    "${session}")" || return 1
  e2e_expect_ok "set tenant MarkPrice override ${location}" "${response}"
}

e2e_clear_mark_override() {
  local location="$1" session="$2"
  [[ -n "${session}" ]] || return 0
  e2e_api_call MDSvr e2eMarkPriceOverride "${location}\\u001f4\\u001fBTCUSDT" \
    "{\"action\":\"CLEAR\",\"token\":\"${MDSVR_E2E_MARK_PRICE_OVERRIDE_TOKEN}\",\"location\":\"${location}\",\"securityID\":\"BTCUSDT\"}" \
    "${session}" >/dev/null 2>&1 || true
}

e2e_wait_port() {
  local port="$1" service="$2" start
  start="$(date +%s)"
  until python3 - "${port}" <<'PY' >/dev/null 2>&1
import socket,sys
s=socket.socket(); s.settimeout(1)
try: ok=s.connect_ex(("127.0.0.1",int(sys.argv[1])))==0
finally: s.close()
raise SystemExit(0 if ok else 1)
PY
  do
    if (( $(date +%s) - start >= 120 )); then
      docker logs --tail 120 "${service}" >&2 || true
      return 1
    fi
    sleep 2
  done
}

e2e_wait_route() {
  local location="$1" server="$2" start response content='{}' key=''
  start="$(date +%s)"
  if [[ "${server}" == "OrderSvr" ]]; then
    content="{\"Location\":\"${location}\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\"}"
    key=",\"key\":\"${location}\\u001f4\\u001fBTCUSDT\""
  fi
  while true; do
    response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
      --data "{\"serverName\":\"${server}\",\"method\":\"__e2e_readiness__\"${key},\"content\":${content}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && ! grep -Eq 'is not Online|PARTITION_NOT_READY|STALE_PARTITION' <<<"${response}"; then
      return 0
    fi
    if (( $(date +%s) - start >= 120 )); then
      return 1
    fi
    sleep 2
  done
}
