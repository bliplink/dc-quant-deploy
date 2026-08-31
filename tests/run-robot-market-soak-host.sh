#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
STATE_DIR="${ROBOT_SOAK_STATE_DIR:-/data/dc-saas-runtime/robot-soak}"
LOCATION="${ROBOT_SOAK_LOCATION:-WEB_E2E}"
ROBOT_USER="${ROBOT_SOAK_ROBOT_USER:-robotsoakmaker}"
ROBOT_ID="${ROBOT_SOAK_ROBOT_ID:-continuous-depth10}"
VIEWER="${ROBOT_SOAK_VIEWER:-robotsoak01}"
TRADERS=(robotsoak01 robotsoak02 robotsoak03 robotsoak04)
PID_FILE="${STATE_DIR}/load.pid"
SECRET_FILE="${STATE_DIR}/runtime.env"
LOG_FILE="${STATE_DIR}/load.log"
METRICS_FILE="${STATE_DIR}/depth-metrics.csv"
MONITOR_CONTAINER="${ROBOT_SOAK_MONITOR_CONTAINER:-dc-saas-robot-web-monitor}"
MONITOR_IMAGE="${ROBOT_SOAK_MONITOR_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"
MODE="${1:-status}"

log() { printf '[robot-soak] %s\n' "$*"; }
die() { printf '[robot-soak] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
safe_identifier "${LOCATION}" || die "Unsafe location"
safe_identifier "${ROBOT_USER}" || die "Unsafe robot user"
safe_identifier "${ROBOT_ID}" || die "Unsafe robot id"
for user in "${TRADERS[@]}"; do safe_identifier "${user}" || die "Unsafe trader user"; done

umask 077
mkdir -p "${STATE_DIR}"
touch "${LOG_FILE}"
chmod 600 "${LOG_FILE}"

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
    curl -fsS --max-time 20 -H 'Content-Type: application/json' -H "sessionId: ${token}" \
      --data "${payload}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
  else
    curl -fsS --max-time 20 -H 'Content-Type: application/json' \
      --data "${payload}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/"
  fi
}

json_field() {
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {"d":d}))' "$1"
}

ensure_secret() {
  if [[ ! -s "${SECRET_FILE}" ]]; then
    printf 'ROBOT_SOAK_PASSWORD=%s\n' "$(openssl rand -hex 24)" >"${SECRET_FILE}"
    chmod 600 "${SECRET_FILE}"
  fi
  # shellcheck disable=SC1090
  . "${SECRET_FILE}"
  [[ -n "${ROBOT_SOAK_PASSWORD:-}" ]] || die "Protected Robot soak password is empty"
}

login_user() {
  local user="$1" response token
  response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"SYS.ATS.LOGIN\",\"content\":{\"method\":\"login\",\"cid\":\"ROBOT_SOAK_${user}\",\"user_id\":\"${user}\",\"user_name\":\"${user}\",\"password\":\"${ROBOT_SOAK_PASSWORD}\",\"client_type\":\"WEB\",\"Location\":\"${LOCATION}\"}}")"
  token="$(printf '%s' "${response}" | json_field 'd.get("data",{}).get("token","")')"
  [[ -n "${token}" ]] || die "Login failed for ${user}: ${response}"
  printf '%s' "${token}"
}

provision() {
  ensure_secret
  local password_hash collision robot_token robot_api response
  password_hash="$(printf '%s' "${ROBOT_SOAK_PASSWORD}" | sha256sum | awk '{print $1}')"
  collision="$(mysql_exec -e "SELECT COUNT(*) FROM dc.dc_users WHERE user_id IN ('${ROBOT_USER}','robotsoak01','robotsoak02','robotsoak03','robotsoak04') AND COALESCE(location,'')<>'${LOCATION}';" dc)"
  [[ "${collision}" == "0" ]] || die "A dedicated Robot soak identity belongs to another location"
  {
    cat <<SQL
START TRANSACTION;
INSERT INTO dc.dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${ROBOT_USER}','${ROBOT_USER}','Continuous Robot Maker','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-soak','${LOCATION}'),
  ('robotsoak01','robotsoak01','Robot Soak Trader 01','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-soak','${LOCATION}'),
  ('robotsoak02','robotsoak02','Robot Soak Trader 02','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-soak','${LOCATION}'),
  ('robotsoak03','robotsoak03','Robot Soak Trader 03','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-soak','${LOCATION}'),
  ('robotsoak04','robotsoak04','Robot Soak Trader 04','${password_hash}','1','1',NOW(),NOW(),'1','1','1','robot-soak','${LOCATION}')
ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',enable_trade='1',update_time=NOW();
INSERT IGNORE INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${ROBOT_USER}',1000000,0,0,0,NOW(),'robot-soak','${LOCATION}'),
  ('robotsoak01',1000000,0,0,0,NOW(),'robot-soak','${LOCATION}'),
  ('robotsoak02',1000000,0,0,0,NOW(),'robot-soak','${LOCATION}'),
  ('robotsoak03',1000000,0,0,0,NOW(),'robot-soak','${LOCATION}'),
  ('robotsoak04',1000000,0,0,0,NOW(),'robot-soak','${LOCATION}');
INSERT INTO dc.dc_users_symbol_config
  (user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES
  ('${ROBOT_USER}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak01','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak02','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak03','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak04','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'robot-soak','${LOCATION}','4')
ON DUPLICATE KEY UPDATE leverage=20,position_type='Cross',update_time=NOW();
UPDATE dc.dc_tenant_symbol ts
JOIN dc.dc_symbol s ON s.symbol=ts.security_id
SET ts.tick_size=COALESCE(ts.tick_size,CAST(s.tick_size AS DECIMAL(36,18))),
    ts.qty_tick_size=COALESCE(ts.qty_tick_size,CAST(s.qty_tick_size AS DECIMAL(36,18))),
    ts.min_order_qty=COALESCE(ts.min_order_qty,CAST(s.min_order_qty AS DECIMAL(36,18))),
    ts.max_order_qty=COALESCE(ts.max_order_qty,CAST(s.max_order_qty AS DECIMAL(36,18))),
    ts.min_notional=COALESCE(ts.min_notional,CAST(s.min_notional AS DECIMAL(36,18))),
    ts.market_take_bound=COALESCE(ts.market_take_bound,CAST(s.market_take_bound AS DECIMAL(36,18))),
    ts.maker_commission=COALESCE(ts.maker_commission,CAST(s.maker_commission AS DECIMAL(36,18))),
    ts.taker_commission=COALESCE(ts.taker_commission,CAST(s.taker_commission AS DECIMAL(36,18))),
    ts.funding_interval=COALESCE(ts.funding_interval,s.funding_interval),
    ts.update_by='robot-soak',ts.update_time=NOW()
WHERE ts.location='${LOCATION}' AND ts.security_id='BTCUSDT';
COMMIT;
SQL
  } | mysql_exec dc

  robot_api="$(mysql_exec -e "SELECT api_key FROM dc.dc_users_api WHERE location='${LOCATION}' AND user_id='${ROBOT_USER}' AND enable='1' ORDER BY update_time DESC LIMIT 1;" dc)"
  if [[ -z "${robot_api}" ]]; then
    robot_token="$(login_user "${ROBOT_USER}")"
    response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"updateApiKey\",\"content\":{\"cid\":\"ROBOT_SOAK_KEY\",\"type\":\"trade\",\"inf1\":\"continuous robot market soak\"}}" "${robot_token}")"
    robot_api="$(printf '%s' "${response}" | json_field 'd.get("data",{}).get("api_key","")')"
    [[ -n "${robot_api}" ]] || die "Could not create Robot API key: ${response}"
  fi

  {
    cat <<SQL
INSERT INTO dc.dc_tenant_robot
  (location,robot_id,robot_name,security_id,api_user_id,api_key,quote_source,enabled,bid_levels,ask_levels,
   level_spread_bps,level_step_bps,order_qty,max_position_qty,refresh_interval_ms,stale_price_ms,
   max_deviation_bps,circuit_breaker_seconds,hedge_enabled,strategy_config,runtime_status,
   create_by,update_by,create_time,update_time)
VALUES
  ('${LOCATION}','${ROBOT_ID}','Continuous Binance 10-Level Market','BTCUSDT','${ROBOT_USER}','${robot_api}',
   'APSSVR_BINANCE_TICKER',1,10,10,2,1,0.001,2,200,3000,500,5,0,
   JSON_OBJECT('sweep_user_orders_enabled',true,'sweep_max_loss_bps',5,'sweep_max_qty',0.001),
   'STOPPED','robot-soak','robot-soak',NOW(),NOW())
ON DUPLICATE KEY UPDATE
  api_user_id=VALUES(api_user_id),api_key=VALUES(api_key),quote_source=VALUES(quote_source),enabled=1,
  bid_levels=10,ask_levels=10,level_spread_bps=2,level_step_bps=1,order_qty=0.001,max_position_qty=2,
  refresh_interval_ms=200,stale_price_ms=3000,max_deviation_bps=500,circuit_breaker_seconds=5,
  hedge_enabled=0,strategy_config=VALUES(strategy_config),update_by='robot-soak',update_time=NOW();
SQL
  } | mysql_exec dc
}

start_monitor() {
  local revision current_revision state
  revision="$(sha256sum "${SCRIPT_DIR}/robot-market-soak-web-monitor.js" | awk '{print $1}')"
  state="$(docker inspect --format '{{.State.Status}}' "${MONITOR_CONTAINER}" 2>/dev/null || true)"
  current_revision="$(docker inspect --format '{{index .Config.Labels "dc.saas.robot-soak-revision"}}' "${MONITOR_CONTAINER}" 2>/dev/null || true)"
  if [[ -n "${state}" && "${current_revision}" != "${revision}" ]]; then
    docker rm -f "${MONITOR_CONTAINER}" >/dev/null
    state=""
  fi
  if [[ -z "${state}" ]]; then
    docker run -d --name "${MONITOR_CONTAINER}" --restart unless-stopped --network host \
      --label dc.saas.role=robot-web-monitor --label "dc.saas.robot-soak-revision=${revision}" \
      -e ROBOT_SOAK_BASE_URL="http://127.0.0.1:${WEB_LISTEN_PORT}" \
      -e ROBOT_SOAK_LOCATION="${LOCATION}" -e ROBOT_SOAK_VIEWER="${VIEWER}" \
      -e ROBOT_SOAK_SECRET_FILE=/secrets/runtime.env -e ROBOT_SOAK_STATE_DIR=/state \
      -v "${SCRIPT_DIR}:/work:ro" -v "${SECRET_FILE}:/secrets/runtime.env:ro" -v "${STATE_DIR}:/state" \
      -v dc-saas-web-e2e-npm-cache:/root/.npm -v dc-saas-web-e2e-runner:/runner \
      "${MONITOR_IMAGE}" bash -lc \
      'cd /runner && [[ -d node_modules/playwright ]] || npm install --no-audit --no-fund playwright@1.55.0 >/dev/null; NODE_PATH=/runner/node_modules node /work/robot-market-soak-web-monitor.js' >/dev/null
  elif [[ "${state}" != "running" ]]; then
    docker start "${MONITOR_CONTAINER}" >/dev/null
  fi
}

cancel_all() {
  local user="$1" token="$2"
  api_call "{\"serverName\":\"OrderSvr\",\"method\":\"cancelAllOrder\",\"content\":{\"UserID\":\"${user}\",\"SecurityID\":\"BTCUSDT\",\"MarketIndicator\":\"4\",\"AlgoName\":\"robot-soak-user\",\"Location\":\"${LOCATION}\"}}" "${token}" >/dev/null 2>&1 || true
}

run_loop() {
  provision
  start_monitor
  declare -A tokens
  local user response code cycle=0 rejected=0 accepted=0 gap_samples=0 action_files=() ever_running=0
  local bid_levels ask_levels best_bid best_ask robot_status web_status now clid price token side
  for user in "${TRADERS[@]}"; do tokens["${user}"]="$(login_user "${user}")"; done
  if [[ ! -s "${METRICS_FILE}" ]]; then
    printf 'time,bid_levels,ask_levels,robot_status,web_http,accepted,rejected,gap_samples\n' >"${METRICS_FILE}"
  fi
  log "Continuous load started: location=${LOCATION}, robot=${ROBOT_ID}, pid=$$"
  while true; do
    read -r bid_levels ask_levels best_bid best_ask robot_status <<<"$(mysql_exec -e "
SELECT
 COUNT(DISTINCT CASE WHEN o.side='Buy' AND o.ord_status IN ('New','Partially_Filled') THEN o.price END),
 COUNT(DISTINCT CASE WHEN o.side='Sell' AND o.ord_status IN ('New','Partially_Filled') THEN o.price END),
 COALESCE(MAX(CASE WHEN o.side='Buy' AND o.ord_status IN ('New','Partially_Filled') THEN o.price END),0),
 COALESCE(MIN(CASE WHEN o.side='Sell' AND o.ord_status IN ('New','Partially_Filled') THEN o.price END),0),
 COALESCE((SELECT runtime_status FROM dc.dc_tenant_robot r WHERE r.location='${LOCATION}' AND r.robot_id='${ROBOT_ID}'),'MISSING')
FROM dc.dc_orders o WHERE o.location='${LOCATION}' AND o.user_id='${ROBOT_USER}'
 AND o.clord_id LIKE 'RBcontinuousd%' AND o.clord_id NOT LIKE '%-SW%';" dc)"
    web_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${WEB_LISTEN_PORT}/#/trade?location=${LOCATION}" || true)"
    [[ "${robot_status}" == "RUNNING" && "${bid_levels}" -ge 10 && "${ask_levels}" -ge 10 ]] && ever_running=1
    if (( ever_running == 1 && (bid_levels < 10 || ask_levels < 10) )); then
      gap_samples=$((gap_samples + 1))
      log "DEPTH_GAP bid=${bid_levels} ask=${ask_levels} status=${robot_status} best=${best_bid}/${best_ask}"
    fi
    now="$(date '+%Y-%m-%dT%H:%M:%S.%3N%z')"
    printf '%s,%s,%s,%s,%s,%s,%s,%s\n' "${now}" "${bid_levels}" "${ask_levels}" "${robot_status}" "${web_status}" "${accepted}" "${rejected}" "${gap_samples}" >>"${METRICS_FILE}"

    if [[ "${robot_status}" == "RUNNING" && "${best_bid}" != "0" && "${best_ask}" != "0" ]]; then
      action_files=()
      for slot in 0 1 2 3; do
        user="${TRADERS[$(((cycle + slot) % ${#TRADERS[@]}))]}"
        token="${tokens[${user}]}"
        clid="SOAK-$(date +%s)-${cycle}-${slot}"
        if (( slot == 0 )); then side=Buy; price="${best_ask}"; tif=IOC
        elif (( slot == 1 )); then side=Sell; price="${best_bid}"; tif=IOC
        elif (( slot == 2 )); then
          side=Sell; tif=GTC
          price="$(python3 - "${best_bid}" "${best_ask}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
b,a=map(Decimal,sys.argv[1:])
p=((b+a)/2).quantize(Decimal('0.01'),rounding=ROUND_DOWN)
if p<=b:p=b+Decimal('0.01')
if p>=a:p=a-Decimal('0.01')
print(p)
PY
)"
        else side=Buy; price="$(python3 -c "from decimal import Decimal; print(Decimal('${best_bid}')-Decimal('10'))")"; tif=GTC
        fi
        file="${STATE_DIR}/response-${slot}.json"
        action_files+=("${file}")
        api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"RobotSoak\",\"AlgoName\":\"robot-soak-user\",\"Side\":\"${side}\",\"Price\":\"${price}\",\"UserID\":\"${user}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"${tif}\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${token}" >"${file}" 2>&1 &
      done
      wait || true
      for file in "${action_files[@]}"; do
        code="$(python3 - "${file}" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1])).get('code',-1))
except Exception: print(-1)
PY
)"
        if [[ "${code}" == "0" ]]; then accepted=$((accepted + 1)); else rejected=$((rejected + 1)); fi
      done
      if (( cycle % 10 == 9 )); then
        for user in "${TRADERS[@]}"; do cancel_all "${user}" "${tokens[${user}]}"; done
      fi
      cycle=$((cycle + 1))
    fi
    sleep 1
  done
}

is_running() { [[ -s "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; }

case "${MODE}" in
  run)
    printf '%s\n' "$$" >"${PID_FILE}"
    trap 'rm -f "${PID_FILE}"' EXIT
    run_loop >>"${LOG_FILE}" 2>&1
    ;;
  start)
    ensure_secret
    if ! is_running; then
      nohup "$0" run >/dev/null 2>&1 &
      sleep 2
    fi
    start_monitor
    is_running || die "Load process did not start"
    log "running pid=$(cat "${PID_FILE}"); monitor=$(docker inspect --format '{{.State.Status}}' "${MONITOR_CONTAINER}")"
    ;;
  stop)
    if is_running; then kill "$(cat "${PID_FILE}")"; fi
    docker rm -f "${MONITOR_CONTAINER}" >/dev/null 2>&1 || true
    log "stopped; Robot configuration remains enabled"
    ;;
  install)
    line="* * * * * cd ${DEPLOY_DIR} && ./tests/run-robot-market-soak-host.sh start >> ${STATE_DIR}/watchdog.log 2>&1 # dc-saas-robot-soak"
    (crontab -l 2>/dev/null | grep -v 'dc-saas-robot-soak' || true; printf '%s\n' "${line}") | crontab -
    "$0" start
    log "watchdog installed in root crontab"
    ;;
  status)
    if is_running; then log "load=running pid=$(cat "${PID_FILE}")"; else log "load=stopped"; fi
    log "web-monitor=$(docker inspect --format '{{.State.Status}}' "${MONITOR_CONTAINER}" 2>/dev/null || echo missing)"
    mysql_exec -e "SELECT location,robot_id,enabled,runtime_status,open_order_count,last_error_code,last_error_message,update_time FROM dc.dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}';" dc || true
    tail -5 "${METRICS_FILE}" 2>/dev/null || true
    ;;
  *) die "Usage: $0 {install|start|run|status|stop}" ;;
esac
