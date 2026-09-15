#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
STATE_DIR="${ROBOT_SOAK_STATE_DIR:-/data/dc-saas-runtime/robot-soak}"
SECRET_FILE="${STATE_DIR}/runtime.env"
LOCATION="${ROBOT_SOAK_LOCATION:-WEB_E2E}"
SYMBOLS=(BTCUSDT ETHUSDT SOLUSDT UNIUSDT)
TRADERS=(robotsoak01 robotsoak02 robotsoak03 robotsoak04)
PID_FILE="${STATE_DIR}/multisymbol-trade.pid"
LOCK_FILE="${STATE_DIR}/multisymbol-trade.lock"
LOG_FILE="${STATE_DIR}/multisymbol-trade.log"
MODE="${1:-status}"

log() { printf '[robot-multisymbol-soak] %s\n' "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -r "${SECRET_FILE}" ]] || die "Run the primary Robot soak provisioner first"
mkdir -p "${STATE_DIR}"
umask 077
touch "${LOG_FILE}"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
# shellcheck disable=SC1090
. "${SECRET_FILE}"
set +a
[[ -n "${ROBOT_SOAK_PASSWORD:-}" ]] || die "Protected Robot soak password is empty"

# shellcheck source=order-routing-key.sh
. "${SCRIPT_DIR}/order-routing-key.sh"

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -N "$@"
}

api_call() {
  local payload="$1" token="${2:-}" symbol="${3:-BTCUSDT}"
  payload="$(dc_attach_order_routing_key "${payload}" "${LOCATION}" 4 "${symbol}")"
  local headers=(-H 'Content-Type: application/json')
  [[ -z "${token}" ]] || headers+=(-H "sessionId: ${token}")
  curl -fsS --max-time 20 "${headers[@]}" --data "${payload}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
}

login_user() {
  local user="$1" response
  response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"SYS.ATS.LOGIN\",\"content\":{\"method\":\"login\",\"cid\":\"ROBOT_MULTI_${user}\",\"user_id\":\"${user}\",\"user_name\":\"${user}\",\"password\":\"${ROBOT_SOAK_PASSWORD}\",\"client_type\":\"WEB\",\"Location\":\"${LOCATION}\"}}")"
  printf '%s' "${response}" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("data") or {}).get("token", ""))'
}

provision_symbols() {
  local values="" user symbol separator=""
  for user in "${TRADERS[@]}"; do
    for symbol in "${SYMBOLS[@]}"; do
      values+="${separator}('${user}','${symbol}','${symbol}',2,'Cross',NOW(),'robot-multisymbol-soak','${LOCATION}','4')"
      separator=","
    done
  done
  mysql_exec dc <<SQL >/dev/null
INSERT INTO dc_users_symbol_config
  (user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES ${values}
ON DUPLICATE KEY UPDATE leverage=VALUES(leverage),position_type=VALUES(position_type),update_time=NOW();
SQL
}

order_qty() {
  local symbol="$1" price="$2" rules
  rules="$(mysql_exec -e "SELECT qty_tick_size,min_order_qty,min_notional FROM dc.dc_tenant_symbol WHERE location='${LOCATION}' AND security_id='${symbol}' LIMIT 1;" dc)"
  [[ -n "${rules}" ]] || return 1
  python3 - "${price}" ${rules} <<'PY'
from decimal import Decimal, ROUND_UP
import sys
price, step, minimum, notional = map(Decimal, sys.argv[1:])
qty = max(minimum, notional / price if price else minimum)
qty = (qty / step).to_integral_value(rounding=ROUND_UP) * step
print(format(qty, 'f'))
PY
}

run_loop() {
  provision_symbols
  declare -A tokens
  local user symbol market best_bid best_ask qty side price reply code clid side_offset cycle=0
  for user in "${TRADERS[@]}"; do
    tokens["${user}"]="$(login_user "${user}")"
    [[ -n "${tokens[${user}]}" ]] || die "Login failed for ${user}"
  done
  log "continuous four-symbol trade load started"
  while true; do
    for index in "${!SYMBOLS[@]}"; do
      symbol="${SYMBOLS[${index}]}"
      market="$(api_call "{\"serverName\":\"MDSvr\",\"method\":\"queryPublicMarket\",\"content\":{\"securityID\":\"${symbol}\",\"location\":\"${LOCATION}\"}}" "" "${symbol}" 2>/dev/null || true)"
      read -r best_bid best_ask <<<"$(printf '%s' "${market}" | python3 -c 'import json,sys
try:
 rows=(((json.load(sys.stdin).get("data") or {}).get("orderBook") or {}).get("NoMDEntries") or [])
 def f(x,*n):
  return next((str(x[k]) for k in n if x.get(k) is not None), "")
 bids=[f(x,"MDEntryPx","mdEntryPx","price") for x in rows if f(x,"MDEntryType","mdEntryType")=="0"]
 asks=[f(x,"MDEntryPx","mdEntryPx","price") for x in rows if f(x,"MDEntryType","mdEntryType")=="1"]
 print(max(bids,key=float) if bids else 0,min(asks,key=float) if asks else 0)
except Exception: print(0,0)')"
      [[ "${best_bid}" != 0 && "${best_ask}" != 0 ]] || { log "NO_DEPTH symbol=${symbol}"; continue; }
      qty="$(order_qty "${symbol}" "${best_ask}")" || { log "NO_RULES symbol=${symbol}"; continue; }
      for side in Buy Sell; do
        [[ "${side}" == Buy ]] && side_offset=0 || side_offset=1
        user="${TRADERS[$(((cycle + index + side_offset) % ${#TRADERS[@]}))]}"
        [[ "${side}" == Buy ]] && price="${best_ask}" || price="${best_bid}"
        clid="SOAK-${symbol}-$(date +%s%N)-${side}"
        reply="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"${qty}\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"RobotSoak\",\"AlgoName\":\"robot-multisymbol-soak\",\"Side\":\"${side}\",\"Price\":\"${price}\",\"UserID\":\"${user}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"IOC\",\"SecurityID\":\"${symbol}\",\"Location\":\"${LOCATION}\"}}" "${tokens[${user}]}" "${symbol}" 2>/dev/null || true)"
        code="$(printf '%s' "${reply}" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("code",-1))
except Exception: print(-1)')"
        log "ORDER symbol=${symbol} side=${side} qty=${qty} code=${code}"
        if [[ "${code}" == 1004 ]]; then tokens["${user}"]="$(login_user "${user}")"; fi
      done
    done
    cycle=$((cycle + 1))
    sleep "${ROBOT_SOAK_MULTISYMBOL_INTERVAL_SECONDS:-2}"
  done
}

is_running() { [[ -s "${PID_FILE}" ]] && kill -0 "$(<"${PID_FILE}")" 2>/dev/null; }
case "${MODE}" in
  run)
    exec 9>"${LOCK_FILE}"; flock -n 9 || exit 0
    printf '%s\n' "$$" >"${PID_FILE}"
    trap 'rm -f "${PID_FILE}"' EXIT
    run_loop >>"${LOG_FILE}" 2>&1
    ;;
  start)
    is_running || nohup "$0" run >/dev/null 2>&1 &
    sleep 2
    is_running || die "load process did not start"
    log "running pid=$(<"${PID_FILE}")"
    ;;
  stop)
    is_running && kill "$(<"${PID_FILE}")" || true
    rm -f "${PID_FILE}"
    log stopped
    ;;
  install)
    line="* * * * * cd ${DEPLOY_DIR} && ./tests/run-robot-multisymbol-trade-soak-host.sh start >> ${STATE_DIR}/watchdog.log 2>&1 # dc-saas-robot-multisymbol-soak"
    (crontab -l 2>/dev/null | grep -v 'dc-saas-robot-multisymbol-soak' || true; printf '%s\n' "${line}") | crontab -
    "$0" start
    ;;
  status) is_running && log "running pid=$(<"${PID_FILE}")" || log stopped; tail -20 "${LOG_FILE}" ;;
  *) die "Usage: $0 {install|start|run|status|stop}" ;;
esac
