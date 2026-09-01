#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
STATE_DIR="${ROBOT_SOAK_STATE_DIR:-/data/dc-saas-runtime/robot-soak}"
LOCATION="${ROBOT_SOAK_LOCATION:-WEB_E2E}"
ROBOT_USER="${ROBOT_SOAK_ROBOT_USER:-robotsoakmaker}"
ROBOT_ID="${ROBOT_SOAK_ROBOT_ID:-continuous-depth10}"
VIEWER="${ROBOT_SOAK_VIEWER:-${ROBOT_USER}}"
TRADERS=(robotsoak01 robotsoak02 robotsoak03 robotsoak04)
PID_FILE="${STATE_DIR}/load.pid"
LOCK_FILE="${STATE_DIR}/load.lock"
SECRET_FILE="${STATE_DIR}/runtime.env"
LOG_FILE="${STATE_DIR}/load.log"
METRICS_FILE="${STATE_DIR}/depth-metrics.csv"
METRICS_HEADER='time,bid_levels,ask_levels,robot_status,web_http,accepted,rejected,gap_samples,auth_refreshes'
CACHE_MARKER="${STATE_DIR}/accounts-loaded.marker"
MONITOR_CONTAINER="${ROBOT_SOAK_MONITOR_CONTAINER:-dc-saas-robot-web-monitor}"
MONITOR_IMAGE="${ROBOT_SOAK_MONITOR_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"
MONITOR_HEARTBEAT_FILE="${STATE_DIR}/web-heartbeat.json"
MONITOR_STALE_SECONDS="${ROBOT_SOAK_MONITOR_STALE_SECONDS:-150}"
AUTH_REFRESH_SECONDS="${ROBOT_SOAK_AUTH_REFRESH_SECONDS:-2700}"
MODE="${1:-status}"

log() { printf '[robot-soak] %s\n' "$*"; }
die() { printf '[robot-soak] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ "$(id -u)" -eq 0 ]] || die "Run as root"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v flock >/dev/null || die "flock is required"
safe_identifier "${LOCATION}" || die "Unsafe location"
safe_identifier "${ROBOT_USER}" || die "Unsafe robot user"
safe_identifier "${ROBOT_ID}" || die "Unsafe robot id"
for user in "${TRADERS[@]}"; do safe_identifier "${user}" || die "Unsafe trader user"; done
[[ "${MONITOR_STALE_SECONDS}" =~ ^[1-9][0-9]*$ ]] || die "ROBOT_SOAK_MONITOR_STALE_SECONDS must be positive"
[[ "${AUTH_REFRESH_SECONDS}" =~ ^[1-9][0-9]*$ ]] || die "ROBOT_SOAK_AUTH_REFRESH_SECONDS must be positive"

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
  local password_hash collision robot_token robot_api tape_token tape_api response initial_load robot_enabled
  initial_load=0
  [[ -s "${CACHE_MARKER}" ]] || initial_load=1
  robot_enabled=1
  (( initial_load == 1 )) && robot_enabled=0
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
  ('${ROBOT_USER}','BTCUSDT','BTCUSDT',2,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak01','BTCUSDT','BTCUSDT',2,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak02','BTCUSDT','BTCUSDT',2,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak03','BTCUSDT','BTCUSDT',2,'Cross',NOW(),'robot-soak','${LOCATION}','4'),
  ('robotsoak04','BTCUSDT','BTCUSDT',2,'Cross',NOW(),'robot-soak','${LOCATION}','4')
ON DUPLICATE KEY UPDATE leverage=2,position_type='Cross',update_time=NOW();
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
  tape_api="$(mysql_exec -e "SELECT api_key FROM dc.dc_users_api WHERE location='${LOCATION}' AND user_id='robotsoak01' AND enable='1' ORDER BY update_time DESC LIMIT 1;" dc)"
  if [[ -z "${tape_api}" ]]; then
    tape_token="$(login_user 'robotsoak01')"
    response="$(api_call '{"serverName":"LoginSvr","method":"updateApiKey","content":{"cid":"ROBOT_TAPE_KEY","type":"trade","inf1":"Binance volume tape"}}' "${tape_token}")"
    tape_api="$(printf '%s' "${response}" | json_field 'd.get("data",{}).get("api_key","")')"
    [[ -n "${tape_api}" ]] || die "Could not create Robot tape API key: ${response}"
  fi

  {
    cat <<SQL
INSERT INTO dc.dc_tenant_robot
  (location,robot_id,robot_name,security_id,api_user_id,api_key,quote_source,enabled,bid_levels,ask_levels,
   level_spread_bps,level_step_bps,order_qty,max_position_qty,refresh_interval_ms,stale_price_ms,
   max_deviation_bps,circuit_breaker_seconds,hedge_enabled,strategy_config,runtime_status,
   create_by,update_by,create_time,update_time)
VALUES
  ('${LOCATION}','${ROBOT_ID}','Continuous Binance 20-Level Market','BTCUSDT','${ROBOT_USER}','${robot_api}',
   'APSSVR_BINANCE_DEPTH',${robot_enabled},20,20,2,1,0.001,10,1000,3000,500,5,0,
   JSON_OBJECT('depth_quantity_mode','NOTIONAL_ZONES','depth_margin_budget',100000,'depth_leverage',2,
     'depth_zone_levels',JSON_ARRAY(6,6,8),'depth_zone_weights',JSON_ARRAY(3,3,4),
     'sweep_user_orders_enabled',true,'sweep_max_loss_bps',5,'sweep_max_qty',0.001,
     'tape_enabled',true,'tape_api_user_id','robotsoak01','tape_api_key','${tape_api}',
     'tape_volume_scale',0.01,'tape_min_notional',5,'tape_max_notional',1000,'tape_interval_ms',1000),
   'STOPPED','robot-soak','robot-soak',NOW(),NOW())
ON DUPLICATE KEY UPDATE
  api_user_id=VALUES(api_user_id),api_key=VALUES(api_key),quote_source=VALUES(quote_source),enabled=${robot_enabled},
  bid_levels=20,ask_levels=20,level_spread_bps=2,level_step_bps=1,order_qty=0.001,max_position_qty=10,
  refresh_interval_ms=1000,stale_price_ms=3000,max_deviation_bps=500,circuit_breaker_seconds=5,
  hedge_enabled=0,strategy_config=VALUES(strategy_config),update_by='robot-soak',update_time=NOW();
SQL
  } | mysql_exec dc

  if (( initial_load == 1 )); then
    log "Loading dedicated Robot soak accounts into LoginSvr/OrderSvr/TradeSvr caches once."
    docker restart dc-saas-loginsvr dc-saas-ordersvr dc-saas-tradesvr >/dev/null
    sleep 8
    docker restart dc-saas-gateway >/dev/null
    for _ in $(seq 1 60); do
      response="$(api_call '{"serverName":"LoginSvr","method":"__robot_soak_readiness__","content":{}}' 2>/dev/null || true)"
      if [[ -n "${response}" && "${response}" != *'is not Online'* ]]; then break; fi
      sleep 2
    done
    [[ -n "${response}" && "${response}" != *'is not Online'* ]] || die "LoginSvr did not become routable"
    printf '%s\n' "$(date -Is)" >"${CACHE_MARKER}"
    mysql_exec -e "UPDATE dc.dc_tenant_robot SET enabled=1,update_by='robot-soak',update_time=NOW() WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}';" dc >/dev/null
  fi
}

start_monitor() {
  local revision current_revision state now heartbeat_time started_at started_epoch
  revision="$(sha256sum "${SCRIPT_DIR}/robot-market-soak-web-monitor.js" | awk '{print $1}')"
  state="$(docker inspect --format '{{.State.Status}}' "${MONITOR_CONTAINER}" 2>/dev/null || true)"
  current_revision="$(docker inspect --format '{{index .Config.Labels "dc.saas.robot-soak-revision"}}' "${MONITOR_CONTAINER}" 2>/dev/null || true)"
  if [[ -n "${state}" && "${current_revision}" != "${revision}" ]]; then
    docker rm -f "${MONITOR_CONTAINER}" >/dev/null
    state=""
  fi
  if [[ "${state}" == "running" ]]; then
    now="$(date +%s)"
    if [[ -f "${MONITOR_HEARTBEAT_FILE}" ]]; then
      heartbeat_time="$(stat -c %Y "${MONITOR_HEARTBEAT_FILE}")"
      if (( now - heartbeat_time > MONITOR_STALE_SECONDS )); then
        log "Web monitor heartbeat is stale by $((now - heartbeat_time))s; recreating the monitor container."
        docker rm -f "${MONITOR_CONTAINER}" >/dev/null
        state=""
      fi
    else
      started_at="$(docker inspect --format '{{.State.StartedAt}}' "${MONITOR_CONTAINER}" 2>/dev/null || true)"
      started_epoch="$(date -d "${started_at}" +%s 2>/dev/null || echo "${now}")"
      if (( now - started_epoch > MONITOR_STALE_SECONDS )); then
        log "Web monitor produced no heartbeat within ${MONITOR_STALE_SECONDS}s; recreating the monitor container."
        docker rm -f "${MONITOR_CONTAINER}" >/dev/null
        state=""
      fi
    fi
  fi
  if [[ -z "${state}" ]]; then
    rm -f "${MONITOR_HEARTBEAT_FILE}" "${MONITOR_HEARTBEAT_FILE}".*.tmp
    docker run -d --name "${MONITOR_CONTAINER}" --restart unless-stopped --network host \
      --memory "${ROBOT_SOAK_MONITOR_MEMORY_LIMIT:-768m}" \
      --cpus "${ROBOT_SOAK_MONITOR_CPU_LIMIT:-1.0}" --pids-limit 256 \
      --log-driver json-file --log-opt "max-size=${DOCKER_LOG_MAX_SIZE:-50m}" \
      --log-opt "max-file=${DOCKER_LOG_MAX_FILE:-5}" \
      --label dc.saas.role=robot-web-monitor --label "dc.saas.robot-soak-revision=${revision}" \
      -e ROBOT_SOAK_BASE_URL="http://127.0.0.1:${WEB_LISTEN_PORT}" \
      -e ROBOT_SOAK_LOCATION="${LOCATION}" -e ROBOT_SOAK_VIEWER="${VIEWER}" \
      -e ROBOT_SOAK_WEB_BROWSER_CYCLE_MS="${ROBOT_SOAK_WEB_BROWSER_CYCLE_MS:-600000}" \
      -e ROBOT_SOAK_WEB_OPERATION_TIMEOUT_MS="${ROBOT_SOAK_WEB_OPERATION_TIMEOUT_MS:-15000}" \
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
  local user="$1" token="$2" response ids reply code
  response="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"queryOpenOrder\",\"content\":{\"userid\":\"${user}\",\"securityid\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${token}" 2>/dev/null || true)"
  [[ -n "${response}" ]] || return 0
  while IFS= read -r ids; do
    [[ -n "${ids}" ]] || continue
    reply="$(api_call "{\"serverName\":\"OrderSvr\",\"method\":\"cancelBatchOrder\",\"content\":{\"location\":\"${LOCATION}\",\"userID\":\"${user}\",\"securityID\":\"BTCUSDT\",\"algoName\":\"cross\",\"orderIDs\":${ids}}}" "${token}" 2>/dev/null || true)"
    code="$(printf '%s' "${reply}" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("code",-1))
except Exception: print(-1)')"
    [[ "${code}" == "0" ]] || log "CANCEL_BATCH_REJECT user=${user} code=${code}"
  done < <(printf '%s' "${response}" | python3 -c 'import json,sys
try:
 data=json.load(sys.stdin).get("data") or []
 ids=[str(x.get("OrderID")) for x in data if str(x.get("ClOrdID") or "").startswith("SOAK-") and x.get("OrderID")]
 for i in range(0,len(ids),50): print(json.dumps(ids[i:i+50],separators=(",",":")))
except Exception:
 pass')
}

run_loop() {
  provision
  start_monitor
  declare -A tokens token_login_epoch
  local user response code message cycle=0 rejected=0 accepted=0 gap_samples=0 auth_refreshes=0 ever_running=0
  local -a action_files=() action_users=()
  local bid_levels ask_levels best_bid best_ask robot_status web_status now clid price token side tenant_tick header archive current_epoch
  for user in "${TRADERS[@]}"; do
    tokens["${user}"]="$(login_user "${user}")"
    token_login_epoch["${user}"]="$(date +%s)"
  done
  for user in "${TRADERS[@]}"; do cancel_all "${user}" "${tokens[${user}]}"; done
  tenant_tick="$(mysql_exec -e "SELECT tick_size FROM dc.dc_tenant_symbol WHERE location='${LOCATION}' AND security_id='BTCUSDT';" dc)"
  [[ -n "${tenant_tick}" ]] || die "Tenant BTCUSDT tick size is unavailable"
  header="$(head -n 1 "${METRICS_FILE}" 2>/dev/null || true)"
  if [[ -n "${header}" && "${header}" != "${METRICS_HEADER}" ]]; then
    archive="${STATE_DIR}/depth-metrics-v1-$(date -u +%Y%m%dT%H%M%SZ).csv"
    mv "${METRICS_FILE}" "${archive}"
    log "Archived legacy metrics as ${archive}."
  fi
  if [[ ! -s "${METRICS_FILE}" ]]; then
    printf '%s\n' "${METRICS_HEADER}" >"${METRICS_FILE}"
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
    [[ "${robot_status}" == "RUNNING" && "${bid_levels}" -ge 20 && "${ask_levels}" -ge 20 ]] && ever_running=1
    if (( ever_running == 1 && (bid_levels < 20 || ask_levels < 20) )); then
      gap_samples=$((gap_samples + 1))
      log "DEPTH_GAP bid=${bid_levels} ask=${ask_levels} status=${robot_status} best=${best_bid}/${best_ask}"
    fi
    now="$(date '+%Y-%m-%dT%H:%M:%S.%3N%z')"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "${now}" "${bid_levels}" "${ask_levels}" "${robot_status}" "${web_status}" "${accepted}" "${rejected}" "${gap_samples}" "${auth_refreshes}" >>"${METRICS_FILE}"

    if [[ "${robot_status}" == "RUNNING" && "${best_bid}" != "0" && "${best_ask}" != "0" ]]; then
      action_files=()
      action_users=()
      for slot in 0 1 2 3; do
        user="${TRADERS[$(((cycle + slot) % ${#TRADERS[@]}))]}"
        current_epoch="$(date +%s)"
        if (( current_epoch - ${token_login_epoch[${user}]} >= AUTH_REFRESH_SECONDS )); then
          tokens["${user}"]="$(login_user "${user}")"
          token_login_epoch["${user}"]="$(date +%s)"
          auth_refreshes=$((auth_refreshes + 1))
          log "SESSION_REFRESH proactive user=${user} count=${auth_refreshes}"
        fi
        token="${tokens[${user}]}"
        clid="SOAK-$(date +%s)-${cycle}-${slot}"
        if (( slot == 0 )); then side=Buy; price="${best_ask}"; tif=IOC
        elif (( slot == 1 )); then side=Sell; price="${best_bid}"; tif=IOC
        elif (( slot == 2 )); then
          side=Sell; tif=GTC
          price="$(python3 - "${best_bid}" "${best_ask}" "${tenant_tick}" <<'PY'
from decimal import Decimal, ROUND_DOWN
import sys
b,a=map(Decimal,sys.argv[1:3])
tick=Decimal(sys.argv[3])
p=(((b+a)/2)/tick).to_integral_value(rounding=ROUND_DOWN)*tick
if p<=b:p=b+tick
if p>=a:p=a-tick
print(p)
PY
)"
        else side=Buy; price="$(python3 -c "from decimal import Decimal; print(Decimal('${best_bid}')-Decimal('10'))")"; tif=GTC
        fi
        file="${STATE_DIR}/response-${slot}.json"
        action_files+=("${file}")
        action_users+=("${user}")
        api_call "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"OPEN\",\"OrderQty\":\"0.0001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"RobotSoak\",\"AlgoName\":\"robot-soak-user\",\"Side\":\"${side}\",\"Price\":\"${price}\",\"UserID\":\"${user}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"${tif}\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"${LOCATION}\"}}" "${token}" >"${file}" 2>&1 &
      done
      wait || true
      for slot in "${!action_files[@]}"; do
        file="${action_files[${slot}]}"
        user="${action_users[${slot}]}"
        IFS=$'\t' read -r code message < <(python3 - "${file}" <<'PY'
import json,sys
try:
 d=json.load(open(sys.argv[1]))
 print(f"{d.get('code',-1)}\t{str(d.get('msg','')).replace(chr(9),' ').replace(chr(10),' ')[:240]}")
except Exception as e: print(f"-1\t{type(e).__name__}")
PY
) || true
        if [[ "${code}" == "0" ]]; then
          accepted=$((accepted + 1))
        elif [[ "${code}" == "1004" ]]; then
          tokens["${user}"]="$(login_user "${user}")"
          token_login_epoch["${user}"]="$(date +%s)"
          auth_refreshes=$((auth_refreshes + 1))
          log "SESSION_REFRESH reactive user=${user} count=${auth_refreshes}"
        else
          rejected=$((rejected + 1))
          log "ORDER_REJECT user=${user} code=${code:-missing} message=${message:-missing}"
        fi
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
load_pids() { pgrep -f '^bash (\./tests|/.*/tests)/run-robot-market-soak-host\.sh run$' || true; }

case "${MODE}" in
  run)
    exec 9>"${LOCK_FILE}"
    flock -n 9 || exit 0
    printf '%s\n' "$$" >"${PID_FILE}"
    trap 'rm -f "${PID_FILE}"' EXIT
    run_loop >>"${LOG_FILE}" 2>&1
    ;;
  start)
    ensure_secret
    for _ in $(seq 1 15); do
      is_running && break
      nohup "$0" run >/dev/null 2>&1 &
      sleep 2
    done
    start_monitor
    if [[ -x "${SCRIPT_DIR}/observe-robot-market-soak.sh" ]]; then
      "${SCRIPT_DIR}/observe-robot-market-soak.sh" >/dev/null || log "Observer reported an unhealthy snapshot; see ${STATE_DIR}/alerts.log."
    fi
    is_running || die "Load process did not start"
    log "running pid=$(cat "${PID_FILE}"); monitor=$(docker inspect --format '{{.State.Status}}' "${MONITOR_CONTAINER}")"
    ;;
  stop)
    pids="$(load_pids)"
    if [[ -n "${pids}" ]]; then
      kill ${pids} 2>/dev/null || true
      for _ in $(seq 1 20); do
        pids="$(load_pids)"
        [[ -z "${pids}" ]] && break
        sleep 0.25
      done
      [[ -z "${pids}" ]] || kill -9 ${pids} 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
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
