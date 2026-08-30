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

password_hash="$(printf '%s' "${E2E_PASSWORD}" | sha256sum | awk '{print $1}')"
[[ "${password_hash}" =~ ^[0-9a-f]{64}$ ]] || die "Could not calculate the password hash"

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

collision_count="$({
  cat <<SQL
SELECT COUNT(*)
FROM dc.dc_users
WHERE user_name IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND NOT (
    user_id = user_name
    AND COALESCE(location, '') = '${E2E_LOCATION}'
  );
SQL
} | mysql_exec)"

[[ "${collision_count}" == "0" ]] ||
  die "An E2E username already belongs to another user or location; refusing to overwrite it"

verified_count="$({
  cat <<SQL
START TRANSACTION;
INSERT IGNORE INTO dc.dc_tenant
  (location,tenant_code,tenant_name,status,registration_enabled,admin_console_enabled,
   trade_enabled,base_url,default_locale,create_by,update_by,create_time,update_time)
VALUES
  ('${E2E_LOCATION}','${E2E_LOCATION}','Automated E2E Tenant','TRIAL',1,1,1,
   '/#/login?location=${E2E_LOCATION}','en-US','e2e-bootstrap','e2e-bootstrap',NOW(),NOW());
INSERT IGNORE INTO dc.dc_tenant_symbol
  (location,security_id,market_indicator,enabled,create_by,update_by,create_time,update_time)
VALUES
  ('${E2E_LOCATION}','BTCUSDT','4',1,'e2e-bootstrap','e2e-bootstrap',NOW(),NOW());
DELETE FROM dc.dc_order_idempotency
WHERE location='${E2E_LOCATION}' AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}');
DELETE FROM dc.dc_orders_execorders
WHERE location='${E2E_LOCATION}' AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}');
DELETE FROM dc.dc_orders
WHERE location='${E2E_LOCATION}' AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}');
DELETE FROM dc.dc_orders_position
WHERE location='${E2E_LOCATION}' AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}');
DELETE FROM dc.dc_users_posting
WHERE location='${E2E_LOCATION}' AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}');
DELETE FROM dc.dc_users_balance
WHERE location='${E2E_LOCATION}' AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}');

INSERT INTO dc.dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${E2E_BUYER}','${E2E_BUYER}','Web Buyer','${password_hash}','1','1',NOW(),NOW(),'1','1','1','e2e-bootstrap','${E2E_LOCATION}'),
  ('${E2E_SELLER}','${E2E_SELLER}','Web Seller','${password_hash}','1','1',NOW(),NOW(),'1','1','1','e2e-bootstrap','${E2E_LOCATION}')
ON DUPLICATE KEY UPDATE
  user_id=VALUES(user_id),
  name=VALUES(name),
  password=VALUES(password),
  user_type=VALUES(user_type),
  enable=VALUES(enable),
  update_time=VALUES(update_time),
  enable_trade=VALUES(enable_trade),
  enable_cash_in=VALUES(enable_cash_in),
  enable_cash_out=VALUES(enable_cash_out),
  close_by=VALUES(close_by),
  location=VALUES(location);
COMMIT;

SELECT IF(
  (SELECT COUNT(*) FROM dc.dc_users
   WHERE user_id IN ('${E2E_BUYER}','${E2E_SELLER}')
     AND user_id = user_name
     AND location = '${E2E_LOCATION}'
     AND enable = '1'
     AND password = '${password_hash}') = 2
  AND EXISTS (
    SELECT 1 FROM dc.dc_tenant_symbol
    WHERE location='${E2E_LOCATION}' AND security_id='BTCUSDT' AND enabled=1
  ), 2, 0);
SQL
} | mysql_exec)"

[[ "${verified_count}" == "2" ]] || die "E2E users were not stored with the expected tenant and password hash"
log "Prepared clean accounts ${E2E_BUYER} and ${E2E_SELLER} for location ${E2E_LOCATION}."
