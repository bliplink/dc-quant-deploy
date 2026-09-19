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
admin_password_a="${E2E_ADMIN_PASSWORD_A:-$(openssl rand -hex 16)}"
admin_password_b="${E2E_ADMIN_PASSWORD_B:-$(openssl rand -hex 16)}"
trader_password_a="${E2E_TRADER_PASSWORD_A:-$(openssl rand -hex 16)}"
trader_password_b="${E2E_TRADER_PASSWORD_B:-$(openssl rand -hex 16)}"

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

signed_api_call() {
  local payload="$1" api_key="$2" secret_key="$3" expiry signature
  expiry="$(( $(date +%s%3N) + 60000 ))"
  signature="$(python3 - "${secret_key}" "${payload}" "${expiry}" <<'PY'
import hashlib
import hmac
import sys
secret, body, expiry = sys.argv[1:]
print(hmac.new(secret.encode("utf-8"), (body + expiry).encode("utf-8"), hashlib.sha256).hexdigest())
PY
)"
  curl -fsS --max-time 30 \
    -H 'Content-Type: application/json' \
    -H "cid: TENANT_API_E2E" \
    -H "apikey: ${api_key}" \
    -H "expiry: ${expiry}" \
    -H "signature: ${signature}" \
    --data "${payload}" "http://127.0.0.1:${GW_HTTP_PORT}/api"
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
  payload="$(printf '{"serverName":"ManagerSvr","method":"tenantApproval","content":{"action":"APPROVE","cid":"APPROVE_%s","request_id":"APPROVE_%s","application_id":"%s","expected_version":1,"location":"%s","base_url":"/#/trade?location=%s","admin_username":"%s","admin_password":"%s","symbols":["BTCUSDT"],"max_registered_users":2,"max_tradable_symbols":1,"review_comment":"Automated tenant lifecycle acceptance"}}' \
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

admin_login_a="$(login "${E2E_ADMIN_USER}" "${admin_password_a}" TenantAdmin "${E2E_LOCATION_A}" ADMIN_A_E2E)"
admin_login_b="$(login "${E2E_ADMIN_USER}" "${admin_password_b}" TenantAdmin "${E2E_LOCATION_B}" ADMIN_B_E2E)"
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

admin_trader_key_payload="$(printf '{"serverName":"LoginSvr","method":"updateApiKey","content":{"cid":"ADMIN_TRADER_KEY_E2E","label":"admin-trader-%s","type":"tenant","permissions":"TENANT_WRITE","rate_limit_profile":"TENANT_HIGH"}}' "${E2E_SUFFIX}")"
admin_trader_key_response="$(api_call "${admin_trader_key_payload}" "${admin_token_a}")"
expect_ok "tenant-admin user trader API key creation" "${admin_trader_key_response}"
admin_trader_api_key="$(printf '%s' "${admin_trader_key_response}" | json_eval 'd["data"]["api_key"]')"
admin_trader_api_secret="$(printf '%s' "${admin_trader_key_response}" | json_eval 'd["data"]["secret_key"]')"
[[ "$(printf '%s' "${admin_trader_key_response}" | json_eval 'd["data"]["type"]')" == "trade" ]] ||
  die "trader self-service key accepted caller supplied tenant key type"
[[ "$(printf '%s' "${admin_trader_key_response}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE" ]] ||
  die "trader self-service key accepted caller supplied tenant scope"

admin_trader_login_payload="$(printf '{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"%s","location":"%s","cid":"ADMIN_TRADER_LOGIN_E2E"}}' "${admin_trader_api_key}" "${E2E_LOCATION_A}")"
admin_trader_login_response="$(signed_api_call "${admin_trader_login_payload}" "${admin_trader_api_key}" "${admin_trader_api_secret}")"
expect_ok "tenant-admin user trader API login" "${admin_trader_login_response}"
admin_trader_api_token="$(printf '%s' "${admin_trader_login_response}" | json_eval 'd["data"]["token"]')"
[[ "$(printf '%s' "${admin_trader_login_response}" | json_eval 'd["data"]["client_type"]')" == "API" ]] ||
  die "trader key did not create an API session"
admin_trader_admin_response="$(api_call "${users_payload}" "${admin_trader_api_token}")"
expect_rejected "Trader API session cannot use Tenant Admin role" "${admin_trader_admin_response}"

admin_trader_key_delete_payload="$(printf '{"serverName":"LoginSvr","method":"deleteApiKey","content":{"api_key":"%s","cid":"ADMIN_TRADER_KEY_DELETE_E2E"}}' "${admin_trader_api_key}")"
admin_trader_key_delete_response="$(api_call "${admin_trader_key_delete_payload}" "${admin_token_a}")"
expect_ok "tenant-admin user trader API key cleanup" "${admin_trader_key_delete_response}"
log "Trader API boundary verified: caller-supplied tenant scope ignored; API session denied Tenant control-plane access."

tenant_key_create_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"CREATE","label":"tenant-e2e-%s","cid":"TENANT_KEY_CREATE_E2E"}}' "${E2E_SUFFIX}")"
tenant_key_create_response="$(api_call "${tenant_key_create_payload}" "${admin_token_a}")"
expect_ok "tenant service API key creation" "${tenant_key_create_response}"
tenant_api_key="$(printf '%s' "${tenant_key_create_response}" | json_eval 'd["data"]["api_key"]')"
tenant_api_secret="$(printf '%s' "${tenant_key_create_response}" | json_eval 'd["data"]["secret_key"]')"
[[ -n "${tenant_api_key}" && -n "${tenant_api_secret}" ]] ||
  die "tenant service API key creation did not return key material"

tenant_api_login_payload="$(printf '{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"%s","location":"%s","cid":"TENANT_API_LOGIN_E2E"}}' "${tenant_api_key}" "${E2E_LOCATION_A}")"
tenant_api_login_response="$(signed_api_call "${tenant_api_login_payload}" "${tenant_api_key}" "${tenant_api_secret}")"
expect_ok "tenant service signed API login" "${tenant_api_login_response}"
tenant_api_token="$(printf '%s' "${tenant_api_login_response}" | json_eval 'd["data"]["token"]')"
[[ "$(printf '%s' "${tenant_api_login_response}" | json_eval 'd["data"]["client_type"]')" == "TenantAPI" ]] ||
  die "tenant service key did not create a TenantAPI session"
[[ "$(printf '%s' "${tenant_api_login_response}" | json_eval 'd["data"]["location"]')" == "${E2E_LOCATION_A}" ]] ||
  die "tenant service API login returned another location"

tenant_api_users_response="$(api_call "${users_payload}" "${tenant_api_token}")"
expect_ok "TenantAPI AdminSvr user list" "${tenant_api_users_response}"

tenant_api_order_payload='{"serverName":"OrderSvr","method":"queryOpenOrder","content":{"securityid":"BTCUSDT","marketIndicator":"4","maxOrderCount":1}}'
tenant_api_order_response="$(api_call "${tenant_api_order_payload}" "${tenant_api_token}")"
expect_rejected "TenantAPI OrderSvr access" "${tenant_api_order_response}"

tenant_api_balance_payload='{"serverName":"TradeSvr","method":"queryAccountBalance","content":{}}'
tenant_api_balance_response="$(api_call "${tenant_api_balance_payload}" "${tenant_api_token}")"
expect_rejected "TenantAPI TradeSvr access" "${tenant_api_balance_response}"

tenant_key_delete_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"DELETE","api_key":"%s","cid":"TENANT_KEY_DELETE_E2E"}}' "${tenant_api_key}")"
tenant_key_delete_response="$(api_call "${tenant_key_delete_payload}" "${admin_token_a}")"
expect_ok "tenant service API key cleanup" "${tenant_key_delete_response}"
log "Tenant Service API key boundary verified: signed /api login -> AdminSvr allowed; OrderSvr/TradeSvr denied."

overflow_payload="$(printf '{"serverName":"AdminSvr","method":"tenantUserRegistration","content":{"action":"REGISTER","cid":"OVERFLOW_%s","request_id":"OVERFLOW_%s","location":"%s","username":"overflowtrader","name":"Quota Overflow Trader","email":"overflow-%s@example.com","password":"%s"}}' \
  "${E2E_SUFFIX}" "${E2E_SUFFIX}" "${E2E_LOCATION_A}" "${E2E_SUFFIX}" "${trader_password_a}")"
overflow_response="$(api_call "${overflow_payload}")"
expect_ok "second customer within registered-user quota" "${overflow_response}"
overflow_user_id="$(printf '%s' "${overflow_response}" | json_eval 'd["data"]["user_id"]')"
[[ -n "${overflow_user_id}" && "${overflow_user_id}" != "${user_id_a}" ]] ||
  die "second tenant customer did not return a distinct user_id"

broker_key_create_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"CREATE","type":"broker","label":"broker-e2e-%s","cid":"BROKER_KEY_CREATE_E2E"}}' "${E2E_SUFFIX}")"
broker_key_create_response="$(api_call "${broker_key_create_payload}" "${admin_token_a}")"
expect_ok "broker API key creation" "${broker_key_create_response}"
broker_api_key="$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["api_key"]')"
broker_api_secret="$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["secret_key"]')"
[[ "$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["type"]')" == "broker" ]] ||
  die "broker key creation did not preserve type=broker"
[[ "$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["rate_limit_profile"]')" == "TRADER_STANDARD" ]] ||
  die "broker key does not use Trader trading rate profile"
[[ "$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE,TENANT_READ,TENANT_WRITE,CUSTOMER_CASH" ]] ||
  die "broker key default permission contract drifted"

broker_login_payload="$(printf '{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"%s","location":"%s","cid":"BROKER_LOGIN_E2E"}}' "${broker_api_key}" "${E2E_LOCATION_A}")"
broker_login_response="$(signed_api_call "${broker_login_payload}" "${broker_api_key}" "${broker_api_secret}")"
expect_ok "broker signed API login" "${broker_login_response}"
broker_api_token="$(printf '%s' "${broker_login_response}" | json_eval 'd["data"]["token"]')"
[[ "$(printf '%s' "${broker_login_response}" | json_eval 'd["data"]["client_type"]')" == "TenantAPI" ]] ||
  die "broker key did not create a TenantAPI session"
[[ "$(printf '%s' "${broker_login_response}" | json_eval 'd["data"]["api_key_type"]')" == "broker" ]] ||
  die "broker session lost api_key_type=broker"

broker_admin_response="$(api_call "${users_payload}" "${broker_api_token}")"
expect_ok "Broker API retains Tenant management access" "${broker_admin_response}"
broker_actor_user_id="$(printf '%s' "${broker_login_response}" | json_eval 'd["data"]["user_id"]')"

ENV_FILE="${ENV_FILE}" BROKER_E2E_RUN_ID="${E2E_SUFFIX}" BROKER_E2E_LOCATION="${E2E_LOCATION_A}" BROKER_E2E_ACTOR_USER_ID="${broker_actor_user_id}" BROKER_E2E_API_KEY="${broker_api_key}" BROKER_E2E_API_SECRET="${broker_api_secret}" BROKER_E2E_MAKER_CUSTOMER_ID="${user_id_a}" BROKER_E2E_TAKER_CUSTOMER_ID="${overflow_user_id}" BROKER_E2E_FOREIGN_LOCATION="${E2E_LOCATION_B}" BROKER_E2E_FOREIGN_CUSTOMER_ID="${user_id_b}"   "${SCRIPT_DIR}/run-broker-api-e2e-host.sh"

broker_key_delete_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"DELETE","api_key":"%s","cid":"BROKER_KEY_DELETE_E2E"}}' "${broker_api_key}")"
broker_key_delete_response="$(api_call "${broker_key_delete_payload}" "${admin_token_a}")"
expect_ok "broker API key cleanup" "${broker_key_delete_response}"
log "Broker API boundary verified: management + same-tenant customer trading/cash allowed; foreign tenant rejected."

overquota_payload="$(printf '{"serverName":"AdminSvr","method":"tenantUserRegistration","content":{"action":"REGISTER","cid":"OVERQUOTA_%s","request_id":"OVERQUOTA_%s","location":"%s","username":"overquotatrader","name":"Over Quota Trader","email":"overquota-%s@example.com","password":"%s"}}' \
  "${E2E_SUFFIX}" "${E2E_SUFFIX}" "${E2E_LOCATION_A}" "${E2E_SUFFIX}" "${trader_password_a}")"
overquota_response="$(api_call "${overquota_payload}")"
expect_rejected "tenant registered-customer quota" "${overquota_response}"

symbols_payload="$(printf '{"serverName":"AdminSvr","method":"tenantSymbolAdmin","content":{"action":"LIST","cid":"SYMBOL_LIST_E2E","location":"%s"}}' "${E2E_LOCATION_A}")"
symbols_response="$(api_call "${symbols_payload}" "${admin_token_a}")"
expect_ok "tenant symbol list" "${symbols_response}"
printf '%s' "${symbols_response}" | python3 -c 'import json,sys; rows=json.load(sys.stdin)["data"]; btc=next(r for r in rows if r["security_id"]=="BTCUSDT"); assert int(btc["configured"]) == 1 and int(btc["enabled"]) == 1'

disable_payload="$(printf '{"serverName":"AdminSvr","method":"tenantSymbolAdmin","content":{"action":"DISABLE","cid":"SYMBOL_DISABLE_E2E","request_id":"SYMBOL_DISABLE_%s","location":"%s","security_id":"BTCUSDT"}}' "${E2E_SUFFIX}" "${E2E_LOCATION_A}")"
disable_response="$(api_call "${disable_payload}" "${admin_token_a}")"
expect_ok "tenant disables an entitled symbol" "${disable_response}"
enable_payload="$(printf '{"serverName":"AdminSvr","method":"tenantSymbolAdmin","content":{"action":"ENABLE","cid":"SYMBOL_ENABLE_E2E","request_id":"SYMBOL_ENABLE_%s","location":"%s","security_id":"BTCUSDT"}}' "${E2E_SUFFIX}" "${E2E_LOCATION_A}")"
enable_response="$(api_call "${enable_payload}" "${admin_token_a}")"
expect_ok "tenant enables an entitled symbol" "${enable_response}"

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
SELECT CONCAT('quota_tenants=',COUNT(*)) FROM dc_tenant WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}') AND JSON_EXTRACT(quotas,'$.max_registered_users')=2 AND JSON_EXTRACT(quotas,'$.max_tradable_symbols')=1;
SELECT CONCAT('audits=',COUNT(*)) FROM dc_tenant_audit_log WHERE location IN ('${E2E_LOCATION_A}','${E2E_LOCATION_B}');")"
grep -Fxq 'tenants=2' <<<"${database_summary}" || die "database tenant provisioning assertion failed"
grep -Fxq 'shared_users=2,distinct_ids=2' <<<"${database_summary}" || die "database identity isolation assertion failed"
grep -Fxq 'balances=2' <<<"${database_summary}" || die "database account initialization assertion failed"
grep -Fxq 'symbols=2' <<<"${database_summary}" || die "database product initialization assertion failed"
grep -Fxq 'quota_tenants=2' <<<"${database_summary}" || die "database tenant quota assertion failed"
log "Database assertions: ${database_summary//$'\n'/; }."
log "PASS: application, approval, URLs, registration, RBAC, Tenant Service API key isolation, symbols, records, lifecycle and two-tenant isolation are correct."
log "Acceptance tenants retained for evidence: ${E2E_LOCATION_A}, ${E2E_LOCATION_B}."
