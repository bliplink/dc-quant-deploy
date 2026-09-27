#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
log(){ printf '[default-e2e] %s\n' "$*"; }
die(){ printf '[default-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
set -a; . "${ENV_FILE}"; set +a
[[ "${DEFAULT_E2E_ENABLED:-true}" == "true" ]] || { log "Default E2E bootstrap disabled."; exit 0; }
LOCATION="${DEFAULT_E2E_LOCATION:-E2E001}"
ADMIN_USER="${DEFAULT_E2E_ADMIN_USERNAME:-tenantadmin}"; ADMIN_PASSWORD="${DEFAULT_E2E_ADMIN_PASSWORD:-}"
TRADER_USER="${DEFAULT_E2E_TRADER_USERNAME:-demotrader}"; TRADER_PASSWORD="${DEFAULT_E2E_TRADER_PASSWORD:-}"
ROBOT_USER="${DEFAULT_E2E_ROBOT_USERNAME:-demorobot}"; ROBOT_PASSWORD="${DEFAULT_E2E_ROBOT_PASSWORD:-}"
TAPE_USER="${DEFAULT_E2E_TAPE_USERNAME:-demotape}"; TAPE_PASSWORD="${DEFAULT_E2E_TAPE_PASSWORD:-}"
ROBOT_ID="default-depth10"; TARGET_BALANCE="1000000"; WEB_PORT="${WEB_LISTEN_PORT:-18088}"
API_URL="http://127.0.0.1:${WEB_PORT}/httpapi/"
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,${NO_PROXY}}"; export no_proxy="${NO_PROXY}"
[[ "${LOCATION}" =~ ^[A-Z0-9]{6}$ ]] || die "DEFAULT_E2E_LOCATION must be exactly 6 uppercase A-Z/0-9 characters"

verify_order_cluster_ready() {
  [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local verifier="${SCRIPT_DIR}/tests/verify-order-cluster-state-host.sh"
  [[ -f "${verifier}" ]] || die "Order cluster verifier is missing: ${verifier}"
  if ! /bin/bash "${verifier}" >/dev/null 2>&1; then
    die "Order cluster is not fully READY; recover all partitions before bootstrapping ${LOCATION}."
  fi
}

verify_order_cluster_ready
for value in "${ADMIN_USER}" "${TRADER_USER}" "${ROBOT_USER}" "${TAPE_USER}"; do [[ "${value}" =~ ^[A-Za-z0-9_.@-]{3,45}$ ]] || die "Unsafe username ${value}"; done
for secret in "${ADMIN_PASSWORD}" "${TRADER_PASSWORD}" "${ROBOT_PASSWORD}" "${TAPE_PASSWORD}" "${PLATFORM_ADMIN_PASSWORD:-}"; do [[ ${#secret} -ge 8 ]] || die "Generated passwords must be at least 8 characters"; done
mysql_exec(){ docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -N "$@"; }
api_call(){ local payload="$1" token="${2:-}"; if [[ -n "${token}" ]]; then curl --noproxy '*' -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${token}" --data "${payload}" "${API_URL}"; else curl --noproxy '*' -fsS --max-time 30 -H 'Content-Type: application/json' --data "${payload}" "${API_URL}"; fi; }
json_eval(){ local expression="$1"; python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1],{"d":d}))' "${expression}"; }
expect_ok(){ local name="$1" response="$2"; [[ "$(printf '%s' "${response}" | json_eval 'd.get("code",-1)')" == "0" ]] || die "${name} failed: ${response}"; }
login(){ local u="$1" p="$2" c="$3" l="$4" cid="$5" r; r="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"SYS.ATS.LOGIN\",\"content\":{\"method\":\"login\",\"cid\":\"${cid}\",\"user_id\":\"${u}\",\"user_name\":\"${u}\",\"password\":\"${p}\",\"client_type\":\"${c}\",\"Location\":\"${l}\"}}")"; expect_ok "login ${l}/${u}" "${r}"; printf '%s' "${r}"; }
wait_login(){ local u="$1" p="$2" c="$3" l="$4" cid="$5" r=""; for _ in $(seq 1 90); do r="$(login "${u}" "${p}" "${c}" "${l}" "${cid}" 2>/dev/null || true)"; if [[ -n "${r}" ]] && [[ "$(printf '%s' "${r}" | json_eval 'd.get("code",-1)' 2>/dev/null || true)" == 0 ]]; then printf '%s' "${r}"; return 0; fi; sleep 2; done; return 1; }

ensure_tenant(){
  local exists application response platform_login platform_token
  exists="$(mysql_exec -e "SELECT COUNT(*) FROM dc_tenant WHERE location='${LOCATION}'" dc)"
  if [[ "${exists}" == 0 ]]; then
    log "Creating ${LOCATION} through tenant application/approval."
    response="$(api_call "{\"serverName\":\"ManagerSvr\",\"method\":\"tenantApplication\",\"content\":{\"action\":\"SUBMIT\",\"cid\":\"DEFAULT_E2E_SUBMIT_${LOCATION}\",\"request_id\":\"DEFAULT_E2E_SUBMIT_${LOCATION}\",\"tenant_code\":\"${LOCATION}\",\"organization_name\":\"DC Default E2E Tenant\",\"contact_name\":\"DC Bootstrap\",\"contact_email\":\"default-e2e@acceptance.invalid\",\"expected_users\":20,\"requested_symbols\":[\"BTCUSDT\"],\"requested_trial_days\":365}}")"; expect_ok "submit default tenant" "${response}"
    application="$(printf '%s' "${response}" | json_eval 'd["data"]["application_id"]')"
    platform_login="$(wait_login "${PLATFORM_ADMIN_USERNAME}" "${PLATFORM_ADMIN_PASSWORD}" Manager PLATFORM DEFAULT_E2E_PLATFORM)" || die "Platform login unavailable"
    platform_token="$(printf '%s' "${platform_login}" | json_eval 'd["data"]["token"]')"
    response="$(api_call "{\"serverName\":\"ManagerSvr\",\"method\":\"tenantApproval\",\"content\":{\"action\":\"APPROVE\",\"cid\":\"DEFAULT_E2E_APPROVE_${LOCATION}\",\"request_id\":\"DEFAULT_E2E_APPROVE_${LOCATION}\",\"application_id\":\"${application}\",\"expected_version\":1,\"location\":\"${LOCATION}\",\"base_url\":\"/#/trade?location=${LOCATION}\",\"admin_username\":\"${ADMIN_USER}\",\"admin_password\":\"${ADMIN_PASSWORD}\",\"symbols\":[\"BTCUSDT\"],\"max_registered_users\":20,\"max_tradable_symbols\":4,\"review_comment\":\"Persistent default E2E tenant\"}}" "${platform_token}")"; expect_ok "approve default tenant" "${response}"
  else log "Reusing existing tenant ${LOCATION}."; fi
  mysql_exec dc <<SQL >/dev/null
UPDATE dc_tenant SET status='ACTIVE',registration_enabled=1,admin_console_enabled=1,trade_enabled=1,update_by='default-e2e',update_time=NOW() WHERE location='${LOCATION}';
INSERT INTO dc_tenant_symbol(location,security_id,market_indicator,enabled,tick_size,qty_tick_size,min_order_qty,max_order_qty,min_notional,market_take_bound,maker_commission,taker_commission,funding_interval,create_by,update_by,create_time,update_time)
VALUES('${LOCATION}','BTCUSDT','4',1,0.1,0.0001,0.0001,10,5,0.05,0.0002,0.0006,28800,'default-e2e','default-e2e',NOW(),NOW())
ON DUPLICATE KEY UPDATE enabled=1,tick_size=VALUES(tick_size),qty_tick_size=VALUES(qty_tick_size),min_order_qty=VALUES(min_order_qty),max_order_qty=VALUES(max_order_qty),min_notional=VALUES(min_notional),market_take_bound=VALUES(market_take_bound),maker_commission=VALUES(maker_commission),taker_commission=VALUES(taker_commission),funding_interval=VALUES(funding_interval),update_by='default-e2e',update_time=NOW();
SQL
}

ensure_user(){
  local username="$1" password="$2" name="$3" email="$4" user_id password_hash response
  user_id="$(mysql_exec -e "SELECT user_id FROM dc_users WHERE location='${LOCATION}' AND user_name='${username}' LIMIT 1" dc)"
  if [[ -z "${user_id}" ]]; then
    response="$(api_call "{\"serverName\":\"AdminSvr\",\"method\":\"tenantUserRegistration\",\"content\":{\"action\":\"REGISTER\",\"cid\":\"DEFAULT_E2E_REGISTER_${username}\",\"request_id\":\"DEFAULT_E2E_REGISTER_${username}\",\"location\":\"${LOCATION}\",\"username\":\"${username}\",\"name\":\"${name}\",\"email\":\"${email}\",\"password\":\"${password}\"}}")"; expect_ok "register ${username}" "${response}"
    user_id="$(printf '%s' "${response}" | json_eval 'd["data"]["user_id"]')"
  fi
  [[ "${user_id}" =~ ^[A-Za-z0-9_.@-]{1,64}$ ]] || die "Unsafe user id ${user_id}"
  password_hash="$(printf '%s' "${password}" | sha256sum | awk '{print $1}')"
  mysql_exec dc <<SQL >/dev/null
UPDATE dc_users SET password='${password_hash}',enable='1',enable_trade='1',enable_cash_in='1',enable_cash_out='1',update_time=NOW(),close_by='default-e2e' WHERE location='${LOCATION}' AND user_id='${user_id}';
INSERT INTO dc_users_balance(user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES('${user_id}',0,0,0,0,NOW(),'default-e2e','${LOCATION}') ON DUPLICATE KEY UPDATE update_time=VALUES(update_time);
INSERT INTO dc_users_symbol_config(user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES('${user_id}','BTCUSDT','BTCUSDT',20,'Cross',NOW(),'default-e2e','${LOCATION}','4')
ON DUPLICATE KEY UPDATE leverage=20,position_type='Cross',update_time=NOW(),close_by='default-e2e';
SQL
  printf '%s' "${user_id}"
}

ensure_admin_password(){
  local h; h="$(printf '%s' "${ADMIN_PASSWORD}" | sha256sum | awk '{print $1}')"
  mysql_exec -e "UPDATE dc_users SET password='${h}',enable='1',update_time=NOW(),close_by='default-e2e' WHERE location='${LOCATION}' AND user_name='${ADMIN_USER}'" dc >/dev/null
  [[ "$(mysql_exec -e "SELECT COUNT(*) FROM dc_users WHERE location='${LOCATION}' AND user_name='${ADMIN_USER}' AND enable='1'" dc)" == 1 ]] || die "Tenant admin is missing"
}

fund_to_target(){
  local user_id="$1" token="$2" demo="$3" balance delta response
  balance="$(mysql_exec -e "SELECT COALESCE(balance,0) FROM dc_users_balance WHERE location='${LOCATION}' AND user_id='${user_id}' LIMIT 1" dc)"
  delta="$(python3 - "${TARGET_BALANCE}" "${balance:-0}" <<'PY'
from decimal import Decimal
import sys
target,current=map(Decimal,sys.argv[1:]); d=max(Decimal(0),target-current)
print(d.to_integral_value() if d == d.to_integral_value() else d)
PY
)"
  [[ "${delta}" != 0 ]] || return 0
  response="$(api_call "{\"serverName\":\"TradeSvr\",\"method\":\"cashIn\",\"key\":\"${LOCATION}\",\"content\":{\"Amount\":\"${delta}\",\"UserID\":\"${user_id}\",\"Location\":\"${LOCATION}\",\"Demo\":\"${demo}\",\"Info1\":\"DEFAULT_E2E_BOOTSTRAP\"}}" "${token}")"; expect_ok "fund ${user_id}" "${response}"
}

ensure_trade_api_key(){
  local user_id="$1" token="$2" label="$3" api_key response
  api_key="$(mysql_exec -e "SELECT api_key FROM dc_users_api WHERE location='${LOCATION}' AND user_id='${user_id}' AND LOWER(type)='trade' AND enable='1' ORDER BY create_time DESC LIMIT 1" dc)"
  if [[ -z "${api_key}" ]]; then
    response="$(api_call "{\"serverName\":\"LoginSvr\",\"method\":\"updateApiKey\",\"content\":{\"cid\":\"DEFAULT_E2E_KEY_${label}\",\"type\":\"trade\",\"inf1\":\"Default E2E ${label}\"}}" "${token}")"; expect_ok "create trade API key ${label}" "${response}"
    api_key="$(printf '%s' "${response}" | json_eval 'd["data"]["api_key"]')"
  fi
  [[ -n "${api_key}" ]] || die "No API key for ${label}"
  printf '%s' "${api_key}"
}

ensure_tenant
ensure_admin_password
TRADER_ID="$(ensure_user "${TRADER_USER}" "${TRADER_PASSWORD}" 'Default E2E Trader' 'default-trader@acceptance.invalid')"
ROBOT_IDENTITY="$(ensure_user "${ROBOT_USER}" "${ROBOT_PASSWORD}" 'Default E2E Robot Maker' 'default-robot@acceptance.invalid')"
TAPE_IDENTITY="$(ensure_user "${TAPE_USER}" "${TAPE_PASSWORD}" 'Default E2E Tape Trader' 'default-tape@acceptance.invalid')"
ADMIN_LOGIN="$(wait_login "${ADMIN_USER}" "${ADMIN_PASSWORD}" TenantAdmin "${LOCATION}" DEFAULT_E2E_ADMIN)" || die "Tenant admin login unavailable"
TRADER_LOGIN="$(wait_login "${TRADER_USER}" "${TRADER_PASSWORD}" WEB "${LOCATION}" DEFAULT_E2E_TRADER)" || die "Trader login unavailable"
ROBOT_LOGIN="$(wait_login "${ROBOT_USER}" "${ROBOT_PASSWORD}" WEB "${LOCATION}" DEFAULT_E2E_ROBOT)" || die "Robot login unavailable"
TAPE_LOGIN="$(wait_login "${TAPE_USER}" "${TAPE_PASSWORD}" WEB "${LOCATION}" DEFAULT_E2E_TAPE)" || die "Tape login unavailable"
TRADER_TOKEN="$(printf '%s' "${TRADER_LOGIN}" | json_eval 'd["data"]["token"]')"; TRADER_ID="$(printf '%s' "${TRADER_LOGIN}" | json_eval 'd["data"]["user_id"]')"
ROBOT_TOKEN="$(printf '%s' "${ROBOT_LOGIN}" | json_eval 'd["data"]["token"]')"; ROBOT_IDENTITY="$(printf '%s' "${ROBOT_LOGIN}" | json_eval 'd["data"]["user_id"]')"
TAPE_TOKEN="$(printf '%s' "${TAPE_LOGIN}" | json_eval 'd["data"]["token"]')"; TAPE_IDENTITY="$(printf '%s' "${TAPE_LOGIN}" | json_eval 'd["data"]["user_id"]')"
fund_to_target "${TRADER_ID}" "${TRADER_TOKEN}" 0
fund_to_target "${ROBOT_IDENTITY}" "${ROBOT_TOKEN}" 1
fund_to_target "${TAPE_IDENTITY}" "${TAPE_TOKEN}" 1
ROBOT_API_KEY="$(ensure_trade_api_key "${ROBOT_IDENTITY}" "${ROBOT_TOKEN}" ROBOT)"
TAPE_API_KEY="$(ensure_trade_api_key "${TAPE_IDENTITY}" "${TAPE_TOKEN}" TAPE)"

log "Provisioning persistent ${ROBOT_ID} liquidity worker."
mysql_exec dc <<SQL >/dev/null
INSERT INTO dc_tenant_robot(location,robot_id,robot_name,security_id,api_user_id,api_key,quote_source,enabled,bid_levels,ask_levels,level_spread_bps,level_step_bps,order_qty,max_position_qty,refresh_interval_ms,stale_price_ms,max_deviation_bps,circuit_breaker_seconds,hedge_enabled,strategy_config,runtime_status,create_by,update_by,create_time,update_time)
VALUES('${LOCATION}','${ROBOT_ID}','Default Binance 10-Level Liquidity','BTCUSDT','${ROBOT_IDENTITY}','${ROBOT_API_KEY}','APSSVR_BINANCE_TICKER',1,10,10,1,1,0.001,0.1,200,3000,500,5,0,
 JSON_OBJECT('sweep_user_orders_enabled',true,'sweep_max_loss_bps',5,'sweep_max_qty',0.001,'tape_enabled',true,'tape_api_user_id','${TAPE_IDENTITY}','tape_api_key','${TAPE_API_KEY}','tape_volume_scale',0.01,'tape_min_notional',5,'tape_max_notional',1000,'tape_interval_ms',1000),
 'STOPPED','default-e2e','default-e2e',NOW(),NOW())
ON DUPLICATE KEY UPDATE robot_name=VALUES(robot_name),security_id=VALUES(security_id),api_user_id=VALUES(api_user_id),api_key=VALUES(api_key),quote_source=VALUES(quote_source),enabled=1,bid_levels=10,ask_levels=10,level_spread_bps=1,level_step_bps=1,order_qty=0.001,max_position_qty=0.1,refresh_interval_ms=200,stale_price_ms=3000,max_deviation_bps=500,circuit_breaker_seconds=5,hedge_enabled=0,strategy_config=VALUES(strategy_config),update_by='default-e2e',update_time=NOW();
SQL

ready=0
for _ in $(seq 1 120); do
  read -r status count reference <<<"$(mysql_exec -e "SELECT runtime_status,COALESCE(open_order_count,0),COALESCE(last_reference_price,0) FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc)"
  if [[ "${status:-}" == RUNNING && "${count:-0}" -ge 19 ]] && python3 - "${reference:-0}" <<'PY'
from decimal import Decimal
import sys
raise SystemExit(0 if Decimal(sys.argv[1]) > 0 else 1)
PY
  then ready=1; break; fi
  sleep 1
done
[[ "${ready}" == 1 ]] || { mysql_exec -e "SELECT runtime_status,last_error_code,last_error_message,open_order_count,last_reference_price FROM dc_tenant_robot WHERE location='${LOCATION}' AND robot_id='${ROBOT_ID}'" dc >&2 || true; die "Default E2E Robot did not become RUNNING"; }

CREDENTIAL_FILE="${DEFAULT_E2E_CREDENTIAL_FILE:-${SCRIPT_DIR}/.default-e2e-credentials.txt}"
CREDENTIAL_DIR="$(dirname "${CREDENTIAL_FILE}")"
CREDENTIAL_TMP="$(mktemp)"
umask 077
cat > "${CREDENTIAL_TMP}" <<CREDS
DC SaaS default demo credentials
Platform location: PLATFORM
Platform username: ${PLATFORM_ADMIN_USERNAME}
Platform password: ${PLATFORM_ADMIN_PASSWORD}

Tenant location: ${LOCATION}
Tenant admin username: ${ADMIN_USER}
Tenant admin password: ${ADMIN_PASSWORD}
Trader username: ${TRADER_USER}
Trader password: ${TRADER_PASSWORD}

Trade URL: http://127.0.0.1:${WEB_PORT}/#/trade?location=${LOCATION}
CREDS
chmod 0600 "${CREDENTIAL_TMP}"
if [[ ! -d "${CREDENTIAL_DIR}" ]]; then
  if [[ -w "$(dirname "${CREDENTIAL_DIR}")" ]]; then
    install -d -m 0750 "${CREDENTIAL_DIR}"
  elif command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
    sudo install -d -o "$(id -u)" -g "$(id -g)" -m 0750 "${CREDENTIAL_DIR}"
  else
    rm -f "${CREDENTIAL_TMP}"
    die "Cannot create credential directory ${CREDENTIAL_DIR}"
  fi
fi
if [[ -w "${CREDENTIAL_DIR}" ]]; then
  install -m 0600 "${CREDENTIAL_TMP}" "${CREDENTIAL_FILE}"
elif command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
  sudo install -o "$(id -u)" -g "$(id -g)" -m 0600 "${CREDENTIAL_TMP}" "${CREDENTIAL_FILE}"
else
  rm -f "${CREDENTIAL_TMP}"
  die "Cannot write credential file ${CREDENTIAL_FILE}"
fi
rm -f "${CREDENTIAL_TMP}"
printf '\n============================================================\n'
printf 'DC SaaS default demo is ready\n'
printf '============================================================\n'
printf 'Platform: location=PLATFORM username=%s password=%s\n' "${PLATFORM_ADMIN_USERNAME}" "${PLATFORM_ADMIN_PASSWORD}"
printf 'Tenant:   location=%s username=%s password=%s\n' "${LOCATION}" "${ADMIN_USER}" "${ADMIN_PASSWORD}"
printf 'Trader:   location=%s username=%s password=%s\n' "${LOCATION}" "${TRADER_USER}" "${TRADER_PASSWORD}"
printf 'Robot:    %s / BTCUSDT / RUNNING (Binance via APSSvr)\n' "${ROBOT_ID}"
printf 'Credentials file: %s\n' "${CREDENTIAL_FILE}"
printf '============================================================\n'
