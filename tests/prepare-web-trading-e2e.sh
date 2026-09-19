#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_LOCATION="${E2E_LOCATION:-WEB_E2E}"
E2E_BUYER="${E2E_BUYER:-webbuyer}"
E2E_SELLER="${E2E_SELLER:-webseller}"

log() {
  printf '[web-e2e-prepare] %s\n' "$*"
}

die() {
  printf '[web-e2e-prepare] ERROR: %s\n' "$*" >&2
  exit 1
}

safe_identifier() {
  [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
safe_identifier "${E2E_LOCATION}" || die "E2E_LOCATION contains unsupported characters"
safe_identifier "${E2E_BUYER}" || die "E2E_BUYER contains unsupported characters"
safe_identifier "${E2E_SELLER}" || die "E2E_SELLER contains unsupported characters"
[[ "${E2E_BUYER}" != "${E2E_SELLER}" ]] || die "Buyer and seller must be different users"
[[ "${E2E_LOCATION}" =~ (^|_)E2E($|_) ]] ||
  die "E2E_LOCATION must be an isolated *_E2E location"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}}"
password_hash="$(printf '%s' "${E2E_PASSWORD}" | sha256sum | awk '{print $1}')"
[[ "${password_hash}" =~ ^[0-9a-f]{64}$ ]] || die "Could not calculate the password hash"

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

log "Preparing isolated tenant ${E2E_LOCATION} for public self-service registration."
{
  cat <<SQL
START TRANSACTION;
INSERT INTO dc.dc_tenant
  (location,tenant_code,tenant_name,status,registration_enabled,admin_console_enabled,
   trade_enabled,base_url,default_locale,create_by,update_by,create_time,update_time)
VALUES
  ('${E2E_LOCATION}','${E2E_LOCATION}','Automated E2E Tenant','TRIAL',1,1,1,
   '/#/login?location=${E2E_LOCATION}','en-US','e2e-bootstrap','e2e-bootstrap',NOW(),NOW())
ON DUPLICATE KEY UPDATE
  status='TRIAL',registration_enabled=1,admin_console_enabled=1,trade_enabled=1,
  update_by='e2e-bootstrap',update_time=NOW();
INSERT INTO dc.dc_tenant_symbol
  (location,security_id,market_indicator,enabled,create_by,update_by,create_time,update_time)
VALUES
  ('${E2E_LOCATION}','BTCUSDT','4',1,'e2e-bootstrap','e2e-bootstrap',NOW(),NOW())
ON DUPLICATE KEY UPDATE enabled=1,update_by='e2e-bootstrap',update_time=NOW();
COMMIT;
SQL
} | mysql_exec dc

register_user() {
  local username="$1" role="$2" email request_file response user_id
  email="${role,,}-${E2E_LOCATION,,}@acceptance.invalid"
  request_file="$(mktemp)"
  chmod 0600 "${request_file}"
  python3 - "${E2E_LOCATION}" "${username}" "${role}" "${email}" "${E2E_PASSWORD}" "${request_file}" <<'PY'
import json
import sys
location, username, role, email, password, path = sys.argv[1:]
payload = {
    "serverName": "AdminSvr",
    "method": "tenantUserRegistration",
    "content": {
        "action": "REGISTER",
        "cid": "E2E_REGISTER_" + username,
        "request_id": "E2E_REGISTER_" + username,
        "location": location,
        "username": username,
        "name": "Acceptance " + role,
        "email": email,
        "password": password,
    },
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
PY
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data-binary "@${request_file}" "${E2E_BASE_URL}/httpapi/")" || {
      rm -f "${request_file}"
      die "Public registration request failed for ${username}"
    }
  rm -f "${request_file}"
  user_id="$(python3 - "${response}" "${username}" <<'PY'
import json
import sys
obj = json.loads(sys.argv[1])
username = sys.argv[2]
if int(obj.get("code", -1)) != 0:
    raise SystemExit("registration rejected for %s: %s" % (username, obj))
data = obj.get("data") or {}
user_id = str(data.get("user_id") or "")
if not user_id:
    raise SystemExit("registration returned no user_id for %s: %s" % (username, obj))
print(user_id)
PY
)" || die "Could not validate registration response for ${username}"
  safe_identifier "${user_id}" || die "Registration returned unsafe user_id for ${username}"
  printf '%s' "${user_id}"
}

buyer_id="$(register_user "${E2E_BUYER}" Buyer)"
seller_id="$(register_user "${E2E_SELLER}" Seller)"
[[ "${buyer_id}" != "${seller_id}" ]] || die "Registration returned the same identity for buyer and seller"

log "Resetting only the isolated acceptance accounts while preserving their real registration identities."
{
  cat <<SQL
START TRANSACTION;
DELETE FROM dc.dc_users_session
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
DELETE FROM dc.dc_order_idempotency
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
DELETE FROM dc.dc_orders_execorders
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
DELETE FROM dc.dc_orders
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
DELETE FROM dc.dc_orders_position
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
DELETE FROM dc.dc_users_posting
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
UPDATE dc.dc_users_balance
SET balance=0,used_margin=0,freezed_margin=0,freezed_commission=0,
    update_time=NOW(),close_by='e2e-bootstrap'
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
UPDATE dc.dc_users
SET password='${password_hash}',enable='1',enable_trade='1',
    enable_cash_in='1',enable_cash_out='1',update_time=NOW(),close_by='e2e-bootstrap'
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
COMMIT;
SQL
} | mysql_exec dc

verification="$({
  cat <<SQL
SELECT COUNT(*) FROM dc.dc_users
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${buyer_id}','${seller_id}')
  AND user_name IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND user_type='2' AND enable='1' AND enable_trade='1' AND password='${password_hash}';
SELECT COUNT(*) FROM dc.dc_tenant_user_role
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}')
  AND role_id='TRADER' AND status='ACTIVE';
SELECT COUNT(*) FROM dc.dc_users_balance
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}')
  AND balance=0 AND used_margin=0 AND freezed_margin=0 AND freezed_commission=0;
SELECT COUNT(*) FROM dc.dc_users_config
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}');
SELECT COUNT(*) FROM dc.dc_users_symbol_config
WHERE location='${E2E_LOCATION}' AND user_id IN ('${buyer_id}','${seller_id}')
  AND security_id='BTCUSDT';
SQL
} | mysql_exec dc)"
mapfile -t rows <<<"${verification}"
[[ "${#rows[@]}" -eq 5 ]] || die "Unexpected registration verification output: ${verification}"
[[ "${rows[0]}" == "2" ]] || die "Registered users are incomplete: ${rows[0]}/2"
[[ "${rows[1]}" == "2" ]] || die "Registered TRADER roles are incomplete: ${rows[1]}/2"
[[ "${rows[2]}" == "2" ]] || die "Registered balances are incomplete: ${rows[2]}/2"
(( rows[3] >= 2 )) || die "Registered user configuration is incomplete: ${rows[3]}"
(( rows[4] >= 2 )) || die "Registered BTCUSDT configuration is incomplete: ${rows[4]}"

log "PASS: public registration created real buyer/seller identities buyer_id=${buyer_id} seller_id=${seller_id}."
