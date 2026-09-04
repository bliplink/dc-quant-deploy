#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
LIQ_LOCATION="${LIQ_E2E_LOCATION:-LIQ_E2E}"
OTHER_LOCATION="${LIQ_E2E_OTHER_LOCATION:-${LIQ_LOCATION}_FOREIGN}"
LIQ_USER="${LIQ_E2E_USER:-liq_trigger}"
MAKER_USER="${LIQ_E2E_MAKER:-liq_maker}"
FOREIGN_USER="${LIQ_E2E_FOREIGN_USER:-liq_foreign}"
maker_request=""
liq_test_stopped="false"

log() { printf '[liq-e2e] %s\n' "$*"; }
die() { printf '[liq-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
for value in "${LIQ_LOCATION}" "${OTHER_LOCATION}" "${LIQ_USER}" "${MAKER_USER}" "${FOREIGN_USER}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LIQ_LOCATION}" != "${OTHER_LOCATION}" ]] || die "Liquidation locations must differ"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

cleanup() {
  [[ -z "${maker_request}" ]] || rm -f "${maker_request}"
  if [[ "${liq_test_stopped}" == "true" ]]; then
    docker start dc-saas-liqsvr >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

query_mark_price() {
  local response
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data "{\"serverName\":\"MDSvr\",\"method\":\"queryPublicMarket\",\"content\":{\"securityID\":\"BTCUSDT\",\"Location\":\"${LIQ_LOCATION}\"}}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
    die "Could not query the current tenant MarkPrice"
  printf '%s' "${response}" | python3 -c '
import json,sys
from decimal import Decimal
d=json.load(sys.stdin)
value=Decimal(str(d["data"]["ticker"]["MarkPrice"]))
assert value > 0
print(value)
' || die "MDSvr returned no positive tenant MarkPrice: ${response}"
}

password_hash="$(printf '%s' "${E2E_PASSWORD}" | sha256sum | awk '{print $1}')"

login_user() {
  local user="$1" request response token
  request="$(mktemp)"
  chmod 0600 "${request}"
  printf '{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"%s","user_name":"%s","password":"%s","method":"login","client_type":"WEB","cid":"LIQ_E2E_%s","Location":"%s"}}\n' \
    "${user}" "${user}" "${E2E_PASSWORD}" "${user}" "${LIQ_LOCATION}" >"${request}"
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data-binary "@${request}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" || {
      rm -f "${request}"
      die "Could not authenticate liquidation liquidity user ${user}"
    }
  rm -f "${request}"
  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' <<<"${response}")"
  [[ -n "${token}" ]] || die "Login returned no session token for ${user}: ${response}"
  printf '%s' "${token}"
}

wait_for_port() {
  local port="$1" service="$2" start
  start="$(date +%s)"
  until ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${port}$"; do
    if (( $(date +%s) - start >= 120 )); then
      docker logs --tail 120 "${service}" >&2 || true
      die "${service} did not listen on ${port}"
    fi
    sleep 2
  done
}

wait_for_route() {
  local server="$1" start response
  start="$(date +%s)"
  while true; do
    response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
      --data "{\"serverName\":\"${server}\",\"method\":\"__e2e_readiness__\",\"content\":{}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && ! grep -Fq 'is not Online' <<<"${response}"; then return 0; fi
    if (( $(date +%s) - start >= 120 )); then die "${server} did not become routable"; fi
    sleep 2
  done
}

collision_count="$(mysql_exec -e "
SELECT COUNT(*) FROM dc.dc_users
WHERE user_name='${MAKER_USER}'
  AND (user_id<>user_name OR COALESCE(location,'')<>'${LIQ_LOCATION}');" dc)"
[[ "${collision_count}" == "0" ]] ||
  die "Liquidation maker username belongs to another identity or location"

fixture_mark="$(query_mark_price)"
IFS=$'\t' read -r entry_price initial_balance initial_margin <<<"$(python3 - "${fixture_mark}" <<'PY'
from decimal import Decimal, ROUND_HALF_UP
import sys
mark = Decimal(sys.argv[1])
entry = mark.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
scale = entry / Decimal('60000')
print(f"{entry:f}\t{scale:.16f}\t{entry * Decimal('0.00004'):.16f}")
PY
)"

log "Stopping LiqSvr while the deterministic risk fixture is loaded."
docker stop dc-saas-liqsvr >/dev/null
liq_test_stopped="true"

log "Preparing controlled partial-liquidation accounts in ${LIQ_LOCATION} at live MarkPrice ${fixture_mark}."
{
  cat <<SQL
START TRANSACTION;
DELETE FROM dc.dc_order_idempotency WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_orders_execorders WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_orders WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_orders_position WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_users_posting WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_users_balance WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${FOREIGN_USER}');

INSERT INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${LIQ_USER}',${initial_balance},${initial_margin},0,0,NOW(),'LIQ_E2E','${LIQ_LOCATION}'),
  ('${MAKER_USER}',100000,0,0,0,NOW(),'LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}',${initial_balance},${initial_margin},0,0,NOW(),'LIQ_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${MAKER_USER}','${MAKER_USER}','Liquidation Maker','${password_hash}','1','1',NOW(),NOW(),
   '1','1','1','LIQ_E2E','${LIQ_LOCATION}')
ON DUPLICATE KEY UPDATE
  user_id=VALUES(user_id),name=VALUES(name),password=VALUES(password),enable=VALUES(enable),
  update_time=VALUES(update_time),enable_trade=VALUES(enable_trade),location=VALUES(location);

INSERT INTO dc.dc_orders_position
  (user_id,security_id,symbol,status,position_type,leverage,
   long_position,long_average,long_used_margin,short_position,short_average,short_used_margin,
   long_locked_position,short_locked_position,long_liq_price,short_liq_price,
   update_time,close_by,location)
VALUES
  ('${LIQ_USER}','BTCUSDT','BTCUSDT',0,'Cross',100,
   0.004,${entry_price},${initial_margin},0,0,0,0,0,999999,0,NOW(),'LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}','BTCUSDT','BTCUSDT',0,'Cross',100,
   0.004,${entry_price},${initial_margin},0,0,0,0,0,999999,0,NOW(),'LIQ_E2E','${OTHER_LOCATION}');
COMMIT;
SQL
} | mysql_exec dc

log "Reloading OrderSvr and TradeSvr, then refreshing GW routes."
docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
docker restart dc-saas-gateway >/dev/null
wait_for_route OrderSvr
wait_for_route TDSvr
maker_session="$(login_user "${MAKER_USER}")"

maker_request="$(mktemp)"
cat >"${maker_request}" <<JSON
{"serverName":"OrderSvr","method":"placeOrder","content":{"OCType":"OPEN","OrderQty":"0.001","OrdType":"Limit","ClOrdID":"LIQ-E2E-MAKER-$(date +%s%N)","Terminal":"API","AlgoName":"cross","Side":"Buy","Price":"${entry_price}","UserID":"${MAKER_USER}","MarketIndicator":"4","TimeInForce":"GTC","SecurityID":"BTCUSDT","Location":"${LIQ_LOCATION}"}}
JSON
maker_response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${maker_session}" \
  --data-binary "@${maker_request}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
  die "Could not place liquidation liquidity order"
grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${maker_response}" ||
  die "Liquidity order was rejected: ${maker_response}"

for _ in $(seq 1 30); do
  maker_open="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LIQ_LOCATION}' AND user_id='${MAKER_USER}'
  AND security_id='BTCUSDT' AND ord_status='New' AND leaves_qty=0.001;
SQL
  } | mysql_exec dc)"
  [[ "${maker_open}" == "1" ]] && break
  sleep 1
done
[[ "${maker_open:-0}" == "1" ]] || die "Liquidity order did not rest in the order book"

current_mark="$(query_mark_price)"
current_liq="$(mysql_exec -e "SELECT long_liq_price FROM dc.dc_orders_position
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND security_id='BTCUSDT';" dc)"
if ! python3 - "${current_mark}" "${current_liq}" <<'PY'
from decimal import Decimal
import sys
mark, liq = map(Decimal, sys.argv[1:])
assert liq > 0 and mark <= liq
PY
then
  die "Dynamic fixture is not unsafe after risk refresh: mark=${current_mark}, longLiq=${current_liq}"
fi

log "Starting LiqSvr so the position and tenant mark-price snapshots trigger liquidation."
docker start dc-saas-liqsvr >/dev/null
liq_test_stopped="false"

liquidation_count="0"
for _ in $(seq 1 90); do
  liquidation_count="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}'
  AND security_id='BTCUSDT' AND UPPER(oc_type)='CLOSE' AND reduce_only=1
  AND ord_type='Market' AND timeinforce='IOC' AND close_by='liq_partial' AND ord_status='Filled';
SQL
  } | mysql_exec dc)"
  [[ "${liquidation_count}" == "1" ]] && break
  sleep 2
done
if [[ "${liquidation_count}" != "1" ]]; then
  docker logs --tail 200 dc-saas-liqsvr >&2 || true
  die "LiqSvr did not create a filled reduce-only Market/IOC partial-liquidation order"
fi

verification="$({
  cat <<SQL
SELECT p.long_position,p.long_used_margin,b.used_margin,b.balance
FROM dc.dc_orders_position p
JOIN dc.dc_users_balance b ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LIQ_LOCATION}' AND p.user_id='${LIQ_USER}' AND p.security_id='BTCUSDT';
SELECT last_qty,last_px,fee,realized_pnl FROM dc.dc_orders_execorders
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND UPPER(oc_type)='CLOSE'
ORDER BY create_time DESC LIMIT 1;
SELECT p.long_position,b.balance FROM dc.dc_orders_position p
JOIN dc.dc_users_balance b ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${OTHER_LOCATION}' AND p.user_id='${FOREIGN_USER}' AND p.security_id='BTCUSDT';
SQL
} | mysql_exec dc)"
mapfile -t rows <<<"${verification}"
[[ "${#rows[@]}" -eq 3 ]] || die "Unexpected liquidation verification output: ${verification}"
if ! python3 - "${rows[0]}" "${rows[1]}" "${rows[2]}" "${entry_price}" \
  "${initial_balance}" "${initial_margin}" <<'PY'
from decimal import Decimal
import sys

position, execution, foreign = (row.split('\t') for row in sys.argv[1:4])
entry, initial_balance, initial_margin = map(Decimal, sys.argv[4:7])
qty, position_margin, account_margin, balance = map(Decimal, position)
last_qty, last_px, fee, realized = map(Decimal, execution)
foreign_qty, foreign_balance = map(Decimal, foreign)
epsilon = Decimal('0.00000001')

assert qty == Decimal('0.003')
assert abs(position_margin - account_margin) <= epsilon
assert Decimal('0') < position_margin < initial_margin
assert last_qty == Decimal('0.001')
assert abs(last_px - entry) <= Decimal('0.1')
assert fee < 0 and abs(realized) <= epsilon
assert abs(balance - (initial_balance + fee)) <= epsilon
assert foreign_qty == Decimal('0.004')
assert abs(foreign_balance - initial_balance) <= epsilon
PY
then
  die "Partial liquidation balance/position or tenant-isolation mismatch: ${verification}"
fi

log "PASS: LiqSvr issued a live-price-driven reduce-only Market/IOC partial liquidation and preserved tenant isolation."
