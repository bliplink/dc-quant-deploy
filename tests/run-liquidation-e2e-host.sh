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

log() { printf '[liq-e2e] %s\n' "$*"; }
die() { printf '[liq-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
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

log "Preparing controlled partial-liquidation accounts in ${LIQ_LOCATION}."
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
  ('${LIQ_USER}',1,2.4,0,0,NOW(),'LIQ_E2E','${LIQ_LOCATION}'),
  ('${MAKER_USER}',100000,0,0,0,NOW(),'LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}',1,2.4,0,0,NOW(),'LIQ_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_orders_position
  (user_id,security_id,symbol,status,position_type,leverage,
   long_position,long_average,long_used_margin,short_position,short_average,short_used_margin,
   long_locked_position,short_locked_position,long_liq_price,short_liq_price,
   update_time,close_by,location)
VALUES
  ('${LIQ_USER}','BTCUSDT','BTCUSDT',0,'Cross',100,
   0.004,60000,2.4,0,0,0,0,0,999999,0,NOW(),'LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}','BTCUSDT','BTCUSDT',0,'Cross',100,
   0.004,60000,2.4,0,0,0,0,0,999999,0,NOW(),'LIQ_E2E','${OTHER_LOCATION}');
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

maker_request="$(mktemp)"
trap 'rm -f "${maker_request}"' EXIT
cat >"${maker_request}" <<JSON
{"serverName":"OrderSvr","method":"placeOrder","content":{"OCType":"OPEN","OrderQty":"0.001","OrdType":"Limit","ClOrdID":"LIQ-E2E-MAKER-$(date +%s%N)","Terminal":"API","AlgoName":"cross","Side":"Buy","Price":"60000","UserID":"${MAKER_USER}","MarketIndicator":"4","TimeInForce":"GTC","SecurityID":"BTCUSDT","Location":"${LIQ_LOCATION}"}}
JSON
maker_response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
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

log "Restarting LiqSvr so the position and tenant mark-price snapshots trigger liquidation."
docker restart dc-saas-liqsvr >/dev/null

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
SELECT long_position,long_used_margin FROM dc.dc_orders_position
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND security_id='BTCUSDT';
SELECT COUNT(*) FROM dc.dc_orders_execorders WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}'
  AND UPPER(oc_type)='CLOSE' AND last_qty=0.001;
SELECT long_position FROM dc.dc_orders_position
WHERE location='${OTHER_LOCATION}' AND user_id='${FOREIGN_USER}' AND security_id='BTCUSDT';
SQL
} | mysql_exec dc)"
mapfile -t rows <<<"${verification}"
[[ "${#rows[@]}" -eq 3 ]] || die "Unexpected liquidation verification output: ${verification}"
[[ "${rows[0]}" == $'0.003000000\t1.800000000' ]] || die "Partial liquidation position mismatch: ${rows[0]}"
[[ "${rows[1]}" == "1" ]] || die "Liquidation execution was not persisted: ${rows[1]}"
[[ "${rows[2]}" == "0.004000000" ]] || die "Foreign-tenant position was modified: ${rows[2]}"

log "PASS: LiqSvr issued a reduce-only Market/IOC partial liquidation and preserved tenant isolation."
