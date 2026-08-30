#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_BASE_URL="${E2E_BASE_URL:-}"
E2E_SUFFIX="${E2E_SUFFIX:-$(date +%m%d%H%M%S)}"
E2E_LOCATION_A="${E2E_LOCATION_A:-SAASA_E2E_${E2E_SUFFIX}}"
E2E_LOCATION_B="${E2E_LOCATION_B:-SAASB_E2E_${E2E_SUFFIX}}"
E2E_SHARED_USER="${E2E_SHARED_USER:-sharedtrader}"
E2E_ADMIN_USER="${E2E_ADMIN_USER:-tenantadmin}"

log() {
  printf '[tenant-e2e] %s\n' "$*"
}

die() {
  printf '[tenant-e2e] ERROR: %s\n' "$*" >&2
  exit 1
}

safe_location() {
  [[ "$1" =~ ^[A-Z][A-Z0-9_]{2,29}$ && "$1" == *_E2E_* ]]
}

[[ "$(id -u)" -eq 0 ]] || die "Run with sudo so ${ENV_FILE} remains protected"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
safe_location "${E2E_LOCATION_A}" || die "E2E_LOCATION_A must be an isolated *_E2E_* location"
safe_location "${E2E_LOCATION_B}" || die "E2E_LOCATION_B must be an isolated *_E2E_* location"
[[ "${E2E_LOCATION_A}" != "${E2E_LOCATION_B}" ]] || die "The two E2E locations must differ"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v openssl >/dev/null 2>&1 || die "openssl is required"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/}"
[[ "${E2E_BASE_URL}" == */httpapi/ ]] || E2E_BASE_URL="${E2E_BASE_URL%/}/httpapi/"
platform_user="${PLATFORM_ADMIN_USERNAME:?PLATFORM_ADMIN_USERNAME is required}"
platform_password="${PLATFORM_ADMIN_PASSWORD:?PLATFORM_ADMIN_PASSWORD is required}"
admin_password_a="$(openssl rand -hex 16)"
admin_password_b="$(openssl rand -hex 16)"
trader_password_a="$(openssl rand -hex 16)"
trader_password_b="$(openssl rand -hex 16)"

api_call() {
  local payload="$1" token=""
  if (( $# > 1 )); then token="$2"; fi
  if [[ -n "${token}" ]]; then
    curl -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${token}" \
      --data "${payload}" "${E2E_BASE_URL}"
  else
    curl -fsS --max-time 30 -H 'Content-Type: application/json' \
      --data "${payload}" "${E2E_BASE_URL}"
  fi
}

json_eval() {
  local expression="$1"
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {"d": d}))' "${expression}"
}

code_of() {
  printf '%s' "$1" | json_eval 'd["code"]'
}

expect_ok() {
  local name="$1" response="$2" code
  code="$(code_of "${response}")"
  [[ "${code}" == "0" ]] || die "${name} failed: ${response}"
}

expect_rejected() {
  local name="$1" response="$2" code
  code="$(code_of "${response}")"
  [[ "${code}" != "0" ]] || die "${name} unexpectedly succeeded"
}

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

login() {
  local username="$1" password="$2" client_type="$3" location="$4" cid="$5" payload
  payload="$(printf '{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"method":"login","cid":"%s","user_id":"%s","user_name":"%s","password":"%s","client_type":"%s","Location":"%s"}}' \
    "${cid}" "${username}" "${username}" "${password}" "${client_type}" "${location}")"
  api_call "${payload}"
}

submit_application() {
  local location="$1" email="$2" request_id="$3" payload response
  payload="$(printf '{"serverName":"ManagerSvr","method":"tenantApplication","content":{"action":"SUBMIT","cid":"%s","request_id":"%s","tenant_code":"%s","organization_name":"%s Acceptance Tenant","contact_name":"Automated Acceptance","contact_email":"%s","expected_users":20,"requested_symbols":["BTCUSDT"],"requested_trial_days":30}}' \
    "${request_id}" "${request_id}" "${location}" "${location}" "${email}")"
  response="$(api_call "${payload}")"
  expect_ok "submit ${location}" "${response}"
  printf '%s' "${response}" | json_eval 'd["data"]["application_id"]'
}

approve_application() {
  local application_id="$1" location="$2" admin_password="$3" token="$4" payload response
  payload="$(printf '{"serverName":"ManagerSvr","method":"tenantApproval","content":{"action":"APPROVE","cid":"APPROVE_%s","request_id":"APPROVE_%s","application_id":"%s","expected_version":1,"location":"%s","base_url":"/#/login?location=%s","admin_username":"%s","admin_password":"%s","symbols":["BTCUSDT"],"review_comment":"Automated tenant lifecycle acceptance"}}' \
    "${location}" "${location}" "${application_id}" "${location}" "${location}" "${E2E_ADMIN_USER}" "${admin_password}")"
  response="$(api_call "${payload}" "${token}")"
  expect_ok "approve ${location}" "${response}"
  [[ "$(printf '%s' "${response}" | json_eval 'd["data"]["location"]')" == "${location}" ]] ||
    die "approval returned another location"
}

register_trader() {
  local location="$1" password="$2" email="$3" payload response
  payload="$(printf '{"serverName":"AdminSvr","method":"tenantUserRegistration","content":{"action":"REGISTER","cid":"REGISTER_%s","request_id":"REGISTER_%s","location":"%s","username":"%s","name":"Shared Tenant Trader","email":"%s","password":"%s"}}' \
    "${location}" "${location}" "${location}" "${E2E_SHARED_USER}" "${email}" "${password}")"
  response="$(api_call "${payload}")"
  expect_ok "register ${location}" "${response}"
  printf '%s' "${response}" | json_eval 'd["data"]["user_id"]'
}

log "Checking public pages and gateway routes."
curl -fsS --max-time 20 "${E2E_BASE_URL%/httpapi/}/#/apply" >/dev/null
for service in LoginSvr ManagerSvr AdminSvr; do
  readiness="$(api_call "$(printf '{"serverName":"%s","method":"__tenant_e2e_readiness__","content":{}}' "${service}")" || true)"
  [[ -n "${readiness}" && "${readiness}" != *"is not Online"* ]] || die "${service} is not routable"
done

email_a="tenant-a-${E2E_SUFFIX}@example.com"
email_b="tenant-b-${E2E_SUFFIX}@example.com"
application_a="$(submit_application "${E2E_LOCATION_A}" "${email_a}" "SUBMIT_A_${E2E_SUFFIX}")"
application_b="$(submit_application "${E2E_LOCATION_B}" "${email_b}" "SUBMIT_B_${E2E_SUFFIX}")"
log "Two isolated trial applications were submitted."

unauthorized="$(api_call '{"serverName":"ManagerSvr","method":"tenantApproval","content":{"action":"LIST","cid":"UNAUTHORIZED_E2E","page_num":0,"page_size":1}}')"
expect_rejected "unauthenticated approval list" "${unauthorized}"

platform_login="$(login "${platform_user}" "${platform_password}" Manager PLATFORM PLATFORM_E2E)"
expect_ok "platform manager login" "${platform_login}"
platform_token="$(printf '%s' "${platform_login}" | json_eval 'd["data"]["token"]')"
[[ -n "${platform_token}" ]] || die "platform login returned no token"

approve_application "${application_a}" "${E2E_LOCATION_A}" "${admin_password_a}" "${platform_token}"
approve_application "${application_b}" "${E2E_LOCATION_B}" "${admin_password_b}" "${platform_token}"
log "Both applications were approved and provisioned transactionally."

for status_spec in "${application_a}|${email_a}|${E2E_LOCATION_A}" "${application_b}|${email_b}|${E2E_LOCATION_B}"; do
  IFS='|' read -r application_id email location <<<"${status_spec}"
  status_payload="$(printf '{"serverName":"ManagerSvr","method":"tenantApplication","content":{"action":"STATUS","cid":"STATUS_%s","application_id":"%s","contact_email":"%s"}}' "${location}" "${application_id}" "${email}")"
  status_response="$(api_call "${status_payload}")"
  expect_ok "public status ${location}" "${status_response}"
  [[ "$(printf '%s' "${status_response}" | json_eval 'd["data"]["status"]')" == "APPROVED" ]] ||
    die "public status did not expose approval"
  [[ "$(printf '%s' "${status_response}" | json_eval 'd["data"]["approved_location"]')" == "${location}" ]] ||
    die "public status returned another tenant"
done

user_id_a="$(register_trader "${E2E_LOCATION_A}" "${trader_password_a}" "shared-a-${E2E_SUFFIX}@example.com")"
user_id_b="$(register_trader "${E2E_LOCATION_B}" "${trader_password_b}" "shared-b-${E2E_SUFFIX}@example.com")"
[[ "${user_id_a}" != "${user_id_b}" ]] || die "tenant registrations reused one global user identity"
log "The same username was registered with separate user IDs in both tenants."

admin_login_a="$(login "${E2E_ADMIN_USER}" "${admin_password_a}" WEB "${E2E_LOCATION_A}" ADMIN_A_E2E)"
admin_login_b="$(login "${E2E_ADMIN_USER}" "${admin_password_b}" WEB "${E2E_LOCATION_B}" ADMIN_B_E2E)"
trader_login_a="$(login "${E2E_SHARED_USER}" "${trader_password_a}" WEB "${E2E_LOCATION_A}" TRADER_A_E2E)"
trader_login_b="$(login "${E2E_SHARED_USER}" "${trader_password_b}" WEB "${E2E_LOCATION_B}" TRADER_B_E2E)"
for login_spec in "admin A|${admin_login_a}" "admin B|${admin_login_b}" "trader A|${trader_login_a}" "trader B|${trader_login_b}"; do
  name="${login_spec%%|*}"; response="${login_spec#*|}"; expect_ok "${name} login" "${response}"
done
admin_token_a="$(printf '%s' "${admin_login_a}" | json_eval 'd["data"]["token"]')"
trader_token_a="$(printf '%s' "${trader_login_a}" | json_eval 'd["data"]["token"]')"

cross_password_login="$(login "${E2E_SHARED_USER}" "${trader_password_a}" WEB "${E2E_LOCATION_B}" CROSS_PASSWORD_E2E)"
expect_rejected "cross-tenant password login" "${cross_password_login}"

users_payload="$(printf '{"serverName":"AdminSvr","method":"tenantUserAdmin","content":{"action":"LIST","cid":"USERS_A_E2E","location":"%s","page_num":0,"page_size":20}}' "${E2E_LOCATION_A}")"
users_response="$(api_call "${users_payload}" "${admin_token_a}")"
expect_ok "tenant user list" "${users_response}"
printf '%s' "${users_response}" | python3 -c 'import json,sys; rows=json.load(sys.stdin)["data"]; names={r["username"] for r in rows}; assert {"tenantadmin","sharedtrader"} <= names'

cross_location_payload="$(printf '{"serverName":"AdminSvr","method":"tenantUserAdmin","content":{"action":"LIST","cid":"CROSS_LOCATION_E2E","location":"%s","page_num":0,"page_size":20}}' "${E2E_LOCATION_B}")"
cross_location_response="$(api_call "${cross_location_payload}" "${admin_token_a}")"
expect_rejected "admin cross-location request" "${cross_location_response}"

trader_admin_response="$(api_call "${users_payload}" "${trader_token_a}")"
expect_rejected "trader tenant-admin request" "${trader_admin_response}"

symbols_payload="$(printf '{"serverName":"AdminSvr","method":"tenantSymbolAdmin","content":{"action":"LIST","cid":"SYMBOL_LIST_E2E","location":"%s"}}' "${E2E_LOCATION_A}")"
symbols_response="$(api_call "${symbols_payload}" "${admin_token_a}")"
expect_ok "tenant symbol list" "${symbols_response}"
printf '%s' "${symbols_response}" | python3 -c 'import json,sys; rows=json.load(sys.stdin)["data"]; btc=next(r for r in rows if r["security_id"]=="BTCUSDT"); assert int(btc["configured"]) == 1 and int(btc["enabled"]) == 1'

upsert_payload="$(printf '{"serverName":"AdminSvr","method":"tenantSymbolAdmin","content":{"action":"UPSERT","cid":"SYMBOL_UPSERT_E2E","request_id":"SYMBOL_UPSERT_%s","location":"%s","security_id":"BTCUSDT","enabled":true,"tick_size":"0.1","qty_tick_size":"0.0001","min_order_qty":"0.0001","max_order_qty":"10","min_notional":"5","market_take_bound":"0.05","maker_commission":"0.0002","taker_commission":"0.0006","funding_interval":28800}}' "${E2E_SUFFIX}" "${E2E_LOCATION_A}")"
upsert_response="$(api_call "${upsert_payload}" "${admin_token_a}")"
expect_ok "tenant symbol upsert with legacy blank max_price" "${upsert_response}"

orders_payload="$(printf '{"serverName":"AdminSvr","method":"tenantTradeAdmin","content":{"action":"ORDERS","cid":"TRADE_QUERY_E2E","location":"%s","user_id":"%s","page_num":0,"page_size":20}}' "${E2E_LOCATION_A}" "${user_id_a}")"
orders_response="$(api_call "${orders_payload}" "${admin_token_a}")"
expect_ok "tenant trade record query" "${orders_response}"

settings_payload="$(printf '{"serverName":"AdminSvr","method":"tenantSettingsAdmin","content":{"action":"GET","cid":"SETTINGS_E2E","location":"%s"}}' "${E2E_LOCATION_A}")"
settings_response="$(api_call "${settings_payload}" "${admin_token_a}")"
expect_ok "tenant settings" "${settings_response}"

suspend_payload="$(printf '{"serverName":"ManagerSvr","method":"tenantApproval","content":{"action":"UPDATE_TENANT","cid":"SUSPEND_E2E","request_id":"SUSPEND_%s","location":"%s","status":"SUSPENDED"}}' "${E2E_SUFFIX}" "${E2E_LOCATION_A}")"
suspend_response="$(api_call "${suspend_payload}" "${platform_token}")"
expect_ok "suspend tenant" "${suspend_response}"
suspended_login="$(login "${E2E_SHARED_USER}" "${trader_password_a}" WEB "${E2E_LOCATION_A}" SUSPENDED_LOGIN_E2E)"
expect_rejected "suspended tenant login" "${suspended_login}"

activate_payload="$(printf '{"serverName":"ManagerSvr","method":"tenantApproval","content":{"action":"UPDATE_TENANT","cid":"ACTIVATE_E2E","request_id":"ACTIVATE_%s","location":"%s","status":"ACTIVE","registration_enabled":true,"trade_enabled":true}}' "${E2E_SUFFIX}" "${E2E_LOCATION_A}")"
activate_response="$(api_call "${activate_payload}" "${platform_token}")"
expect_ok "reactivate tenant" "${activate_response}"
reactivated_login="$(login "${E2E_SHARED_USER}" "${trader_password_a}" WEB "${E2E_LOCATION_A}" REACTIVATED_LOGIN_E2E)"
expect_ok "reactivated tenant login" "${reactivated_login}"

database_summary="$(mysql_exec dc -e "
SELECT CONCAT('tenants=',COUNT(*)) FROM dc_tenant WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}');
SELECT CONCAT('shared_users=',COUNT(*),',distinct_ids=',COUNT(DISTINCT user_id)) FROM dc_users WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}') AND user_name='${E2E_SHARED_USER}';
SELECT CONCAT('balances=',COUNT(*)) FROM dc_users_balance WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}') AND user_id IN ('${user_id_a}','${user_id_b}');
SELECT CONCAT('symbols=',COUNT(*)) FROM dc_tenant_symbol WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}') AND security_id='BTCUSDT' AND enabled=1;
SELECT CONCAT('audits=',COUNT(*)) FROM dc_tenant_audit_log WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}');")"
grep -Fxq 'tenants=2' <<<"${database_summary}" || die "database tenant provisioning assertion failed"
grep -Fxq 'shared_users=2,distinct_ids=2' <<<"${database_summary}" || die "database identity isolation assertion failed"
grep -Fxq 'balances=2' <<<"${database_summary}" || die "database account initialization assertion failed"
grep -Fxq 'symbols=2' <<<"${database_summary}" || die "database product initialization assertion failed"
log "Database assertions: ${database_summary//$'\n'/; }."
log "PASS: application, approval, URLs, registration, RBAC, symbols, records, lifecycle and two-tenant isolation are correct."
log "Acceptance tenants retained for evidence: ${E2E_LOCATION_A}, ${E2E_LOCATION_B}."
