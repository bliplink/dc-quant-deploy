#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_BASE_URL="${E2E_BASE_URL:-}"
E2E_SUFFIX="${E2E_SUFFIX:-$(date +%m%d%H%M%S)}"
E2E_LOCATION_SEED="$(python3 - "${E2E_SUFFIX}" <<'PYSEED'
import hashlib,sys
print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:5].upper())
PYSEED
)"
E2E_LOCATION_A="${E2E_LOCATION_A:-A${E2E_LOCATION_SEED}}"
E2E_LOCATION_B="${E2E_LOCATION_B:-B${E2E_LOCATION_SEED}}"
E2E_SHARED_USER="${E2E_SHARED_USER:-sharedtrader}"
E2E_ADMIN_USER="${E2E_ADMIN_USER:-tenantadmin}"

log() {
  # stdout carries machine-readable IDs/JSON from command substitutions.
  # Keep diagnostics on stderr so approvals and registrations receive clean IDs.
  printf '[tenant-e2e] %s\n' "$*" >&2
}

die() {
  printf '[tenant-e2e] ERROR: %s\n' "$*" >&2
  exit 1
}

safe_location() {
  [[ "$1" =~ ^[A-Z0-9]{6}$ ]]
}

# This lifecycle script creates tenants/accounts before invoking Broker E2E.
# Do not create even temporary accounts if the deployed Java Broker runner has
# not passed the immutable-image safety review.
command -v docker >/dev/null 2>&1 || die "docker is required"
reviewed_broker_image="$(docker inspect --format '{{.Image}}' dc-saas-robotsvr 2>/dev/null || true)"
[[ -n "${reviewed_broker_image}" ]] || die "RobotSvr image unavailable for Broker E2E safety review"
python3 "${SCRIPT_DIR}/broker-runner-image-review.py" "${reviewed_broker_image}" ||
  die "Isolated tenant lifecycle blocked before any account registration: Broker runner not approved"

[[ "$(id -u)" -eq 0 ]] || die "Run with sudo so ${ENV_FILE} remains protected"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
safe_location "${E2E_LOCATION_A}" || die "E2E_LOCATION_A must be exactly 6 uppercase A-Z/0-9 characters"
safe_location "${E2E_LOCATION_B}" || die "E2E_LOCATION_B must be exactly 6 uppercase A-Z/0-9 characters"
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
TENANT_PAGE_BASE_URL="${TENANT_PAGE_BASE_URL:-http://127.0.0.1:18092}"
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="${NO_PROXY}"
platform_user="${PLATFORM_ADMIN_USERNAME:?PLATFORM_ADMIN_USERNAME is required}"
platform_password="${PLATFORM_ADMIN_PASSWORD:?PLATFORM_ADMIN_PASSWORD is required}"
admin_password_a="${E2E_ADMIN_PASSWORD_A:-$(openssl rand -hex 16)}"
admin_password_b="${E2E_ADMIN_PASSWORD_B:-$(openssl rand -hex 16)}"
trader_password_a="${E2E_TRADER_PASSWORD_A:-$(openssl rand -hex 16)}"
trader_password_b="${E2E_TRADER_PASSWORD_B:-$(openssl rand -hex 16)}"

api_call() {
  local payload="$1" token=""
  if (( $# > 1 )); then token="$2"; fi
  # Partitioned market/order requests require a top-level GW routing key.
  # Fail closed on any mismatch instead of reporting a false RBAC result.
  if [[ "${payload}" == *'"serverName":"OrderSvr"'* ||
        "${payload}" == *'"serverName":"MDSvr"'* ]]; then
    payload="$(printf '%s' "${payload}" |
      python3 "${SCRIPT_DIR}/gw-partition-route.py" "${E2E_LOCATION_A}")" ||
      die "Could not validate isolated tenant GW partition routing"
  fi
  if [[ -n "${token}" ]]; then
    curl --noproxy '*' -sS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${token}" \
      --data "${payload}" "${E2E_BASE_URL}"
  else
    curl --noproxy '*' -sS --max-time 30 -H 'Content-Type: application/json' \
      --data "${payload}" "${E2E_BASE_URL}"
  fi
}

signed_api_call() {
  local payload="$1" api_key="$2" secret_key="$3" expiry signature
  # Portable on macOS and Linux (Darwin date does not support %3N).
  expiry="$(python3 -c 'import time;print(int(time.time()*1000)+60000)')"
  signature="$(python3 - "${secret_key}" "${payload}" "${expiry}" <<'PY'
import hashlib
import hmac
import sys
secret, body, expiry = sys.argv[1:]
print(hmac.new(secret.encode("utf-8"), (body + expiry).encode("utf-8"), hashlib.sha256).hexdigest())
PY
)"
  # Negative authentication may return HTTP 401/403 with a structured GW code.
  # Retain its body so explicit authorization denial can be asserted.
  curl --noproxy '*' -sS --max-time 30 \
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
  # Never echo entire gateway responses: key-creation responses contain Secret Key.
  [[ "${code}" == "0" ]] || die "${name} failed (GW code=${code})"
  log "PASS: ${name}"
}

expect_rejected() {
  local name="$1" response="$2" code
  code="$(code_of "${response}")"
  [[ "${code}" != "0" ]] || die "${name} unexpectedly succeeded"
  # A rate limiter or unrelated internal failure is not evidence of RBAC denial.
  [[ "${code}" != "10003" ]] || die "${name} was throttled, not denied"
  if [[ "${code}" == "9000" ]]; then
    local message
    message="$(printf '%s' "${response}" | json_eval 'd.get("msg", "")')"
    [[ "${message}" != "INTERNAL_ERROR" ]] ||
      die "${name} returned INTERNAL_ERROR, not an authorization verdict"
  fi
  log "PASS: ${name} (rejected; code=${code})"
}

expect_order_scope_denied() {
  local name="$1" response="$2" code
  code="$(code_of "${response}")"
  [[ "${code}" == "9016" ]] ||
    die "${name} expected TRADE_PERMISSION_DENIED (9016), got GW code=${code}"
  log "PASS: ${name} (ORDER_WRITE missing; code=9016)"
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

# On failed runs, revoke only keys created by these disposable test tenants.
# Never print API secrets, session tokens or the raw gateway response.

# Reconcile an ambiguous order acknowledgement by the run-unique ClOrdID.
# A network error after OrderSvr acceptance must not skip cleanup simply
# because the HTTP caller never received an OrderID. Never resubmit orders.
cleanup_pending_trader_order() {
  [[ -n "${trader_new_clordid:-}" && -n "${trader_write_token:-}" ]] || return 0
  local open_payload open_response found_id cancel_payload cancel_response
  open_payload='{"serverName":"OrderSvr","method":"queryOpenOrder","content":{"securityid":"BTCUSDT","marketIndicator":"4","maxOrderCount":100}}'
  open_response="$(api_call "${open_payload}" "${trader_write_token}" 2>/dev/null)" || {
    log "WARN: could not query potentially accepted test order; manual reconciliation required."
    return 0
  }
  if [[ "$(code_of "${open_response}")" != "0" ]]; then
    log "WARN: activity query rejected during failure cleanup; manual reconciliation required."
    return 0
  fi
  found_id="$(printf '%s' "${open_response}" | python3 -c '
import json,sys
response=json.load(sys.stdin)
rows=response.get("data")
if not isinstance(rows,list):
    raise SystemExit(2)
matches=[r for r in rows if isinstance(r,dict) and
         str(r.get("ClOrdID") or r.get("clord_id") or "")==sys.argv[1]]
if len(matches)>1: raise SystemExit(2)
if matches:
    ident=str(matches[0].get("OrderID") or matches[0].get("order_id") or "")
    if not ident: raise SystemExit(2)
    print(ident)
' "${trader_new_clordid}")" || {
    log "WARN: ambiguous or invalid order snapshot during cleanup; manual reconciliation required."
    return 0
  }
  if [[ -z "${found_id}" ]]; then
    # May have been filled, rejected, or already cancelled. A read-only
    # execution/history reconciliation is still required by E2E auditors.
    log "NOTE: no open test order matched ClOrdID; check executions/history if acknowledgement was ambiguous."
    return 0
  fi
  cancel_payload="$(printf '{"serverName":"OrderSvr","method":"cancelOrder","content":{"SecurityID":"BTCUSDT","MarketIndicator":"4","OrderID":"%s","ClOrdID":"TRADER_FAILURE_CANCEL_%s"}}' "${found_id}" "${E2E_SUFFIX}")"
  cancel_response="$(api_call "${cancel_payload}" "${trader_write_token}" 2>/dev/null)" || {
    log "WARN: cancelling matched test order failed; manual reconciliation required."
    return 0
  }
  if [[ "$(code_of "${cancel_response}")" != "0" ]]; then
    log "WARN: matched test-order cancellation was rejected; manual reconciliation required."
    return 0
  fi
  # Cancellation acknowledgement is not authoritative. Keep polling the
  # same owner's open orders for at most 3 seconds; never try a second order.
  local attempt remaining
  for attempt in {1..10}; do
    open_response="$(api_call "${open_payload}" "${trader_write_token}" 2>/dev/null)" || {
      log "WARN: cancellation submitted but follow-up query failed; manual reconciliation required."
      return 0
    }
    if [[ "$(code_of "${open_response}")" != "0" ]]; then
      log "WARN: cancellation submitted but follow-up was rejected; manual reconciliation required."
      return 0
    fi
    remaining="$(printf '%s' "${open_response}" | python3 -c '
import json,sys
d=json.load(sys.stdin)
rows=d.get("data")
if not isinstance(rows,list): raise SystemExit(2)
matches=[r for r in rows if isinstance(r,dict) and
         str(r.get("ClOrdID") or r.get("clord_id") or "")==sys.argv[1]]
print(len(matches))
' "${trader_new_clordid}")" || {
      log "WARN: cancellation submitted but confirmation was malformed; manual reconciliation required."
      return 0
    }
    if [[ "${remaining}" == "0" ]]; then
      log "PASS: matched test order no longer appears in owning account open orders."
      return 0
    fi
    sleep 0.3
  done
  log "WARN: cancelled test ClOrdID remains open after bounded wait; manual reconciliation required."
}

cleanup_test_key() {
  local owner="$1" key="$2" token="$3" payload
  [[ -n "${key}" && -n "${token}" ]] || return 0
  if [[ "${owner}" == tenant ]]; then
    payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"DELETE","api_key":"%s","cid":"E2E_FAILURE_CLEANUP"}}' "${key}")"
  else
    payload="$(printf '{"serverName":"LoginSvr","method":"deleteApiKey","content":{"api_key":"%s","cid":"E2E_FAILURE_CLEANUP"}}' "${key}")"
  fi
  local response
  if ! response="$(api_call "${payload}" "${token}" 2>/dev/null)" || [[ "$(code_of "${response:-{}}")" != "0" ]]; then
    log "WARN: could not revoke a disposable test key; review isolated acceptance tenant."
  fi
}
cleanup_failed_keys() {
  local previous_code="$1"
  [[ "${previous_code}" -ne 0 ]] || return 0
  set +e
  # Query by unique ClOrdID first, even if no OrderID was returned to us.
  cleanup_pending_trader_order
  cleanup_test_key trader "${trader_readonly_key:-}" "${trader_token_a:-}"
  cleanup_test_key trader "${trader_write_key:-}" "${trader_token_a:-}"
  cleanup_test_key trader "${admin_trader_api_key:-}" "${admin_token_a:-}"
  cleanup_test_key tenant "${tenant_api_key:-}" "${admin_token_a:-}"
  cleanup_test_key tenant "${broker_readonly_key:-}" "${admin_token_a:-}"
  cleanup_test_key tenant "${broker_api_key:-}" "${admin_token_a:-}"
  log "Acceptance script exited with code ${previous_code}; key cleanup attempted."
}
trap 'cleanup_failed_keys "$?"' EXIT

log "Checking the public tenant page. Real login/application/registration calls below are the service readiness gates."
curl --noproxy '*' -fsS --max-time 20 "${TENANT_PAGE_BASE_URL%/}/#/apply" >/dev/null

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

# Trader API key lifecycle on a disposable account in isolated tenant A.
# The key is read-only; every step must remain scoped to the trader login.
trader_readonly_payload="$(printf '{"serverName":"LoginSvr","method":"updateApiKey","content":{"cid":"TRADER_READONLY_E2E","type":"trade","label":"trader-readonly-%s","permissions":"MARKET_READ,ACCOUNT_READ,ORDER_READ"}}' "${E2E_SUFFIX}")"
trader_readonly_created="$(api_call "${trader_readonly_payload}" "${trader_token_a}")"
expect_ok "Trader creates self-service read-only API key" "${trader_readonly_created}"
trader_readonly_key="$(printf '%s' "${trader_readonly_created}" | json_eval 'd["data"]["api_key"]')"
trader_readonly_secret="$(printf '%s' "${trader_readonly_created}" | json_eval 'd["data"]["secret_key"]')"
[[ "$(printf '%s' "${trader_readonly_created}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ" ]] ||
  die "Trader self-service read-only scope changed unexpectedly"
trader_readonly_list="$(api_call '{"serverName":"LoginSvr","method":"queryApiKey","content":{"cid":"TRADER_READONLY_LIST_E2E"}}' "${trader_token_a}")"
expect_ok "Trader lists own keys" "${trader_readonly_list}"
printf '%s' "${trader_readonly_list}" | python3 -c '
import json,sys
d=json.load(sys.stdin)["data"]
assert isinstance(d,list) and d
assert all(not key.get("secret_key") for key in d), "API key list leaked a secret"
'
trader_readonly_login_payload="$(printf '{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"cid":"TRADER_READONLY_LOGIN_E2E","location":"%s","api_key":"%s"}}' "${E2E_LOCATION_A}" "${trader_readonly_key}")"
trader_readonly_session="$(signed_api_call "${trader_readonly_login_payload}" "${trader_readonly_key}" "${trader_readonly_secret}")"
expect_ok "Trader self-service key signed API login" "${trader_readonly_session}"
[[ "$(printf '%s' "${trader_readonly_session}" | json_eval 'd["data"]["client_type"]')" == "API" ]] ||
  die "Trader key must create API client_type"
[[ "$(printf '%s' "${trader_readonly_session}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ" ]] ||
  die "Trader key session broadened permissions"
[[ "$(printf '%s' "${trader_readonly_session}" | json_eval 'd["data"]["location"]')" == "${E2E_LOCATION_A}" ]] ||
  die "Trader signed login crossed tenant"
[[ "$(printf '%s' "${trader_readonly_session}" | json_eval 'd["data"]["user_id"]')" == "${user_id_a}" ]] ||
  die "Trader signed login changed authoritative user ID"
trader_readonly_token="$(printf '%s' "${trader_readonly_session}" | json_eval 'd["data"]["token"]')"
trader_balance="$(api_call '{"serverName":"TradeSvr","method":"queryAccountBalance","content":{}}' "${trader_readonly_token}")"
expect_ok "Trader key queries own account balance" "${trader_balance}"
trader_write_denied_payload="$(printf '{"serverName":"OrderSvr","method":"placeOrder","content":{"SecurityID":"BTCUSDT","MarketIndicator":"4","Side":"BUY","OCType":"OPEN","OrdType":"Limit","TimeInForce":"GTC","OrderQty":"0.001","Price":"60000","ClOrdID":"TRADER_READONLY_BLOCK_%s"}}' "${E2E_SUFFIX}")"
trader_write_denied="$(api_call "${trader_write_denied_payload}" "${trader_readonly_token}")"
expect_order_scope_denied "Trader key without ORDER_WRITE cannot place an order" "${trader_write_denied}"
trader_readonly_delete_payload="$(printf '{"serverName":"LoginSvr","method":"deleteApiKey","content":{"api_key":"%s","cid":"TRADER_READONLY_DELETE_E2E"}}' "${trader_readonly_key}")"
trader_readonly_delete="$(api_call "${trader_readonly_delete_payload}" "${trader_token_a}")"
expect_ok "Trader self-service key revocation" "${trader_readonly_delete}"
sleep 1
trader_revoked_login="$(signed_api_call "${trader_readonly_login_payload}" "${trader_readonly_key}" "${trader_readonly_secret}")"
expect_rejected "Revoked Trader API key cannot sign in again" "${trader_revoked_login}"
log "Trader key acceptance: create, no-secret list, signed login, own-account read, write denial, revoke."



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

broker_readonly_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"CREATE","type":"broker","label":"broker-readonly-default-%s","cid":"BROKER_READONLY_CREATE_E2E"}}' "${E2E_SUFFIX}")"
broker_readonly_response="$(api_call "${broker_readonly_payload}" "${admin_token_a}")"
expect_ok "broker omitted permissions defaults to read-only" "${broker_readonly_response}"
[[ "$(printf '%s' "${broker_readonly_response}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ" ]] ||
  die "Broker key without explicit scopes must never receive order writes, cash or tenant management"
broker_readonly_key="$(printf '%s' "${broker_readonly_response}" | json_eval 'd["data"]["api_key"]')"
broker_readonly_secret="$(printf '%s' "${broker_readonly_response}" | json_eval 'd["data"]["secret_key"]')"
broker_readonly_login_payload="$(printf '{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"%s","location":"%s","cid":"BROKER_READONLY_LOGIN_E2E"}}' "${broker_readonly_key}" "${E2E_LOCATION_A}")"
broker_readonly_login_response="$(signed_api_call "${broker_readonly_login_payload}" "${broker_readonly_key}" "${broker_readonly_secret}")"
expect_ok "broker read-only signed login" "${broker_readonly_login_response}"
[[ "$(printf '%s' "${broker_readonly_login_response}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ" ]] ||
  die "Broker session widened omitted permissions"
broker_readonly_token="$(printf '%s' "${broker_readonly_login_response}" | json_eval 'd["data"]["token"]')"
broker_readonly_admin_response="$(api_call "${users_payload}" "${broker_readonly_token}")"
expect_rejected "read-only broker cannot administer tenant users" "${broker_readonly_admin_response}"
# A read-only Broker session must not submit a customer order. Assert the
# precise permission-denied code, not an unrelated rejection or rate limit.
broker_readonly_order_payload="$(printf '{"serverName":"OrderSvr","method":"placeOrder","content":{"Location":"%s","UserID":"%s","SecurityID":"BTCUSDT","MarketIndicator":"4","Side":"BUY","OCType":"OPEN","OrdType":"Limit","TimeInForce":"GTC","OrderQty":"0.001","Price":"60000","ClOrdID":"BROKER_READONLY_BLOCK_%s"}}' "${E2E_LOCATION_A}" "${user_id_a}" "${E2E_SUFFIX}")"
broker_readonly_order_response="$(api_call "${broker_readonly_order_payload}" "${broker_readonly_token}")"
expect_order_scope_denied "read-only Broker cannot place customer order" "${broker_readonly_order_response}"
broker_readonly_delete_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"DELETE","api_key":"%s","cid":"BROKER_READONLY_DELETE_E2E"}}' "${broker_readonly_key}")"
broker_readonly_delete_response="$(api_call "${broker_readonly_delete_payload}" "${admin_token_a}")"
expect_ok "broker read-only key cleanup" "${broker_readonly_delete_response}"
log "Broker omitted scope -> read-only signed session; tenant control-plane denied."

broker_key_create_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"CREATE","type":"broker","permissions":"MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE,TENANT_READ,TENANT_WRITE,CUSTOMER_CASH","label":"broker-e2e-%s","cid":"BROKER_KEY_CREATE_E2E"}}' "${E2E_SUFFIX}")"
broker_key_create_response="$(api_call "${broker_key_create_payload}" "${admin_token_a}")"
expect_ok "broker API key creation" "${broker_key_create_response}"
broker_api_key="$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["api_key"]')"
broker_api_secret="$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["secret_key"]')"
[[ "$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["type"]')" == "broker" ]] ||
  die "broker key creation did not preserve type=broker"
[[ "$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["rate_limit_profile"]')" == "TRADER_STANDARD" ]] ||
  die "broker key does not use Trader trading rate profile"
[[ "$(printf '%s' "${broker_key_create_response}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE,TENANT_READ,TENANT_WRITE,CUSTOMER_CASH" ]] ||
  die "broker key explicit permission contract drifted"

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

# The Broker runner funded the disposable maker account. Verify that an
# independently issued Trader key with explicit ORDER_WRITE can place and
# cancel its *own* order, without UserID/Location override fields.
trader_write_create_payload="$(printf '{"serverName":"LoginSvr","method":"updateApiKey","content":{"cid":"TRADER_WRITE_E2E","type":"trade","label":"trader-write-%s","permissions":"MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE"}}' "${E2E_SUFFIX}")"
trader_write_created="$(api_call "${trader_write_create_payload}" "${trader_token_a}")"
expect_ok "Trader explicitly creates ORDER_WRITE key" "${trader_write_created}"
trader_write_key="$(printf '%s' "${trader_write_created}" | json_eval 'd["data"]["api_key"]')"
trader_write_secret="$(printf '%s' "${trader_write_created}" | json_eval 'd["data"]["secret_key"]')"
[[ "$(printf '%s' "${trader_write_created}" | json_eval 'd["data"]["permissions"]')" == "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE" ]] ||
  die "Trader write key permissions were not issued as requested"
trader_write_login_payload="$(printf '{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"%s","location":"%s","cid":"TRADER_WRITE_LOGIN_E2E"}}' "${trader_write_key}" "${E2E_LOCATION_A}")"
trader_write_login="$(signed_api_call "${trader_write_login_payload}" "${trader_write_key}" "${trader_write_secret}")"
expect_ok "Trader ORDER_WRITE signed login" "${trader_write_login}"
[[ "$(printf '%s' "${trader_write_login}" | json_eval 'd["data"]["client_type"]')" == "API" ]] ||
  die "Trader write key created the wrong client type"
[[ "$(printf '%s' "${trader_write_login}" | json_eval 'd["data"]["user_id"]')" == "${user_id_a}" ]] ||
  die "Trader write key changed account ownership"
trader_write_token="$(printf '%s' "${trader_write_login}" | json_eval 'd["data"]["token"]')"
trader_new_clordid="TRADER_WRITE_${E2E_SUFFIX}"
trader_write_price="${E2E_TRADER_LIMIT_PRICE:-}"
trader_write_qty="${E2E_TRADER_ORDER_QTY:-0.001}"
if [[ -z "${trader_write_price}" ]]; then
  # A fixed buy price can cross the spread when the demo market moves.
  # Derive a resting price below the current best bid; never submit a
  # second order if the first request becomes ambiguous.
  trader_market_payload="$(printf '{"serverName":"MDSvr","method":"queryPublicMarket","content":{"location":"%s","securityID":"BTCUSDT"}}' "${E2E_LOCATION_A}")"
  trader_market_snapshot="$(api_call "${trader_market_payload}" "${trader_write_token}")"
  expect_ok "Trader fetches price reference for non-crossing limit" "${trader_market_snapshot}"
  trader_write_price="$(printf '%s' "${trader_market_snapshot}" |
    python3 "${SCRIPT_DIR}/trader-resting-price.py")" ||
    die "Could not calculate a safe resting demo limit; no order submitted"
fi
[[ "${trader_write_price}" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
  die "E2E_TRADER_LIMIT_PRICE must be a positive decimal"
[[ "${trader_write_qty}" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
  die "E2E_TRADER_ORDER_QTY must be a positive decimal"
trader_order_payload="$(printf '{"serverName":"OrderSvr","method":"placeOrder","content":{"SecurityID":"BTCUSDT","MarketIndicator":"4","Side":"BUY","OCType":"OPEN","OrdType":"Limit","TimeInForce":"GTC","OrderQty":"%s","Price":"%s","ClOrdID":"%s"}}' "${trader_write_qty}" "${trader_write_price}" "${trader_new_clordid}")"
trader_order_response="$(api_call "${trader_order_payload}" "${trader_write_token}")"
expect_ok "Trader API places own funded limit order" "${trader_order_response}"
# code=0 is admission, not proof of an open order. Wait for the matching
# authoritative OrderSvr open-order row before attempting cancellation.
trader_open_query='{"serverName":"OrderSvr","method":"queryOpenOrder","content":{"securityid":"BTCUSDT","marketIndicator":"4","maxOrderCount":100}}'
trader_order_id=""
for attempt in {1..40}; do
  trader_open_response="$(api_call "${trader_open_query}" "${trader_write_token}")"
  [[ "$(code_of "${trader_open_response}")" == "0" ]] || die "Trader queryOpenOrder after place failed"
  trader_order_id="$(printf '%s' "${trader_open_response}" | python3 -c '
import json,sys
doc=json.load(sys.stdin)
rows=doc.get("data") or []
target=sys.argv[1]
match=next((row for row in rows if str(row.get("ClOrdID") or row.get("clord_id") or "")==target),None)
print(str((match or {}).get("OrderID") or (match or {}).get("order_id") or ""))
' "${trader_new_clordid}")"
  [[ -z "${trader_order_id}" ]] || break
  sleep 0.2
done
[[ -n "${trader_order_id}" ]] ||
  die "Trader order did not become open; reconcile by ClOrdID before retrying (do not resubmit)"
trader_cancel_payload="$(printf '{"serverName":"OrderSvr","method":"cancelOrder","content":{"SecurityID":"BTCUSDT","MarketIndicator":"4","OrderID":"%s","ClOrdID":"TRADER_CANCEL_%s"}}' "${trader_order_id}" "${E2E_SUFFIX}")"
trader_cancel_response="$(api_call "${trader_cancel_payload}" "${trader_write_token}")"
expect_ok "Trader API cancels own limit order" "${trader_cancel_response}"
trader_order_still_open=1
for attempt in {1..40}; do
  trader_open_response="$(api_call "${trader_open_query}" "${trader_write_token}")"
  [[ "$(code_of "${trader_open_response}")" == "0" ]] || die "Trader queryOpenOrder after cancel failed"
  trader_order_still_open="$(printf '%s' "${trader_open_response}" | python3 -c '
import json,sys
doc=json.load(sys.stdin)
target=sys.argv[1]
print(int(any(str(row.get("ClOrdID") or row.get("clord_id") or "")==target for row in (doc.get("data") or []))))
' "${trader_new_clordid}")"
  [[ "${trader_order_still_open}" != 0 ]] || break
  sleep 0.2
done
[[ "${trader_order_still_open}" == 0 ]] ||
  die "Trader cancel accepted but order remains open; test order must be investigated"
trader_write_revoke_payload="$(printf '{"serverName":"LoginSvr","method":"deleteApiKey","content":{"api_key":"%s","cid":"TRADER_WRITE_REVOKE_E2E"}}' "${trader_write_key}")"
trader_write_revoke="$(api_call "${trader_write_revoke_payload}" "${trader_token_a}")"
expect_ok "Trader write key revoked by its owner" "${trader_write_revoke}"
trader_write_login_after_revoke="$(signed_api_call "${trader_write_login_payload}" "${trader_write_key}" "${trader_write_secret}")"
expect_rejected "Trader revoked write key cannot re-authenticate" "${trader_write_login_after_revoke}"
log "Trader write key acceptance: explicit scope, signed login, own-account order, cancel and revoke."



broker_key_delete_payload="$(printf '{"serverName":"LoginSvr","method":"tenantApiKeyAdmin","content":{"action":"DELETE","api_key":"%s","cid":"BROKER_KEY_DELETE_E2E"}}' "${broker_api_key}")"
broker_key_delete_response="$(api_call "${broker_key_delete_payload}" "${admin_token_a}")"
expect_ok "broker API key cleanup" "${broker_key_delete_response}"
broker_revoked_login_response="$(signed_api_call "${broker_login_payload}" "${broker_api_key}" "${broker_api_secret}")"
expect_rejected "revoked Broker API key cannot authenticate again" "${broker_revoked_login_response}"
log "Broker API boundary verified: management, customer trading, cash, tenant isolation, revoked login."

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
