#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
ADL_LOCATION="${ADL_E2E_LOCATION:-ADL_E2E}"
OTHER_LOCATION="${ADL_E2E_OTHER_LOCATION:-ADL_E2E_OTHER}"
ORDER_ID="${ADL_E2E_ORDER_ID:-ADL-E2E-LIQ-001}"
REFERENCE_PRICE="${ADL_E2E_REFERENCE_PRICE:-80}"

log() {
  printf '[adl-e2e] %s\n' "$*"
}

die() {
  printf '[adl-e2e] ERROR: %s\n' "$*" >&2
  exit 1
}

safe_identifier() {
  [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
safe_identifier "${ADL_LOCATION}" || die "ADL_E2E_LOCATION contains unsupported characters"
safe_identifier "${OTHER_LOCATION}" || die "ADL_E2E_OTHER_LOCATION contains unsupported characters"
safe_identifier "${ORDER_ID}" || die "ADL_E2E_ORDER_ID contains unsupported characters"
[[ "${REFERENCE_PRICE}" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
  die "ADL_E2E_REFERENCE_PRICE must be a nonnegative number"
[[ "${ADL_LOCATION}" != "${OTHER_LOCATION}" ]] || die "ADL locations must be different"

high_short_average="$(awk -v price="${REFERENCE_PRICE}" 'BEGIN {printf "%.8f", price + 70}')"
low_short_average="$(awk -v price="${REFERENCE_PRICE}" 'BEGIN {printf "%.8f", price + 40}')"
foreign_short_average="$(awk -v price="${REFERENCE_PRICE}" 'BEGIN {printf "%.8f", price + 120}')"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
    mysql -u"${MYSQL_USERNAME}" -N "$@"
}

wait_for_trade_port() {
  local start
  start="$(date +%s)"
  until ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${TRADESVR_GW_PORT}$"; do
    if (( $(date +%s) - start >= 120 )); then
      docker logs --tail 120 dc-saas-tradesvr >&2 || true
      die "TradeSvr did not listen on ${TRADESVR_GW_PORT}"
    fi
    sleep 2
  done
}

log "Preparing isolated ADL accounts in ${ADL_LOCATION}."
{
  cat <<SQL
START TRANSACTION;
DELETE FROM dc.dc_users_posting WHERE location='${ADL_LOCATION}' AND source_id='${ORDER_ID}';
DELETE FROM dc.dc_adl_ledger WHERE location='${ADL_LOCATION}' AND liquidation_order_id='${ORDER_ID}';
DELETE FROM dc.dc_adl_event WHERE location='${ADL_LOCATION}' AND liquidation_order_id='${ORDER_ID}';
DELETE FROM dc.dc_liquidation_deficit WHERE location='${ADL_LOCATION}' AND liquidation_order_id='${ORDER_ID}';
DELETE FROM dc.dc_orders_position WHERE location IN ('${ADL_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('adl_liquidated','adl_high','adl_low','adl_foreign');
DELETE FROM dc.dc_users_balance WHERE location IN ('${ADL_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('adl_liquidated','adl_high','adl_low','adl_foreign');
DELETE FROM dc.dc_insurance_fund WHERE location='${ADL_LOCATION}' AND security_id='BTCUSDT';

INSERT INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('adl_liquidated',1,1.8,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_high',10,10,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_low',100,20,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_foreign',10,10,0,0,NOW(),'ADL_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_orders_position
  (user_id,security_id,symbol,status,position_type,leverage,
   long_position,long_average,long_used_margin,short_position,short_average,short_used_margin,
   long_locked_position,short_locked_position,long_liq_price,short_liq_price,
   update_time,close_by,location)
VALUES
  ('adl_liquidated','BTCUSDT','BTCUSDT',0,'Cross',100,
   1,180,1.8,0,0,0,1,0,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_high','BTCUSDT','BTCUSDT',0,'Cross',100,
   0,0,0,1,${high_short_average},10,0,0,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_low','BTCUSDT','BTCUSDT',0,'Cross',100,
   0,0,0,1,${low_short_average},20,0,0,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_foreign','BTCUSDT','BTCUSDT',0,'Cross',100,
   0,0,0,2,${foreign_short_average},10,0,0,0,0,NOW(),'ADL_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_insurance_fund(location,security_id,balance,update_time)
VALUES('${ADL_LOCATION}','BTCUSDT',0,NOW());
COMMIT;
SQL
} | mysql_exec

log "Restarting TradeSvr so the controlled balances and positions become its in-memory baseline."
docker restart dc-saas-tradesvr >/dev/null
sleep 2
wait_for_trade_port

request_file="$(mktemp)"
trap 'rm -f "${request_file}"' EXIT
chmod 0600 "${request_file}"
cat >"${request_file}" <<JSON
{"serverName":"TradeSvr","method":"updateOrder","content":{"ExecType":"Trade","ExecID":"ADL-E2E-EXEC-001","OrdStatus":"Filled","OCType":"ClOSE","OrderID":"${ORDER_ID}","SecurityID":"BTCUSDT","UserID":"adl_liquidated","Side":"Sell","LastQty":"1","LastPx":"80","OrigOrdPrice":"80","LeavesQty":"0","Maker":"false","CloseBy":"liq","Location":"${ADL_LOCATION}","Demo":""}}
JSON

response=""
for attempt in $(seq 1 30); do
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data-binary "@${request_file}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
    die "TradeSvr updateOrder request failed"
  if grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}"; then
    break
  fi
  if grep -Fq 'is not Online' <<<"${response}"; then
    sleep 2
    continue
  fi
  die "TradeSvr rejected the liquidation fill: ${response}"
done
grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}" ||
  die "TradeSvr did not become routable through GW: ${response}"

result="$({
  cat <<SQL
SELECT d.status,d.deficit_amount,d.covered_amount,d.adl_covered_amount,d.remaining_amount,
       e.status,e.candidate_count
FROM dc.dc_liquidation_deficit d
JOIN dc.dc_adl_event e
  ON e.location=d.location AND e.liquidation_order_id=d.liquidation_order_id
WHERE d.location='${ADL_LOCATION}' AND d.liquidation_order_id='${ORDER_ID}';
SELECT rank_no,candidate_user_id,position_side,reduced_quantity,allocated_amount
FROM dc.dc_adl_ledger
WHERE location='${ADL_LOCATION}' AND liquidation_order_id='${ORDER_ID}'
ORDER BY rank_no;
SELECT user_id,balance,used_margin
FROM dc.dc_users_balance
WHERE location='${ADL_LOCATION}' AND user_id IN ('adl_liquidated','adl_high','adl_low')
ORDER BY user_id;
SELECT user_id,short_position,short_used_margin
FROM dc.dc_orders_position
WHERE location='${ADL_LOCATION}' AND user_id IN ('adl_high','adl_low')
ORDER BY user_id;
SELECT short_position
FROM dc.dc_orders_position
WHERE location='${OTHER_LOCATION}' AND user_id='adl_foreign' AND security_id='BTCUSDT';
SQL
} | mysql_exec)"

mapfile -t rows <<<"${result}"
[[ "${#rows[@]}" -eq 9 ]] || die "Unexpected ADL verification row count: ${#rows[@]} (${result})"
[[ "${rows[0]}" == $'COMPLETED\t99.0480000000000000\t0.0000000000000000\t99.0480000000000000\t0.0000000000000000\tCOMPLETED\t2' ]] ||
  die "ADL event/deficit mismatch: ${rows[0]}"
[[ "${rows[1]}" == $'1\tadl_high\tSHORT\t1.000000000\t70.0000000000000000' ]] ||
  die "First-ranked candidate mismatch: ${rows[1]}"
[[ "${rows[2]}" == $'2\tadl_low\tSHORT\t0.726200000\t29.0480000000000000' ]] ||
  die "Second-ranked candidate mismatch: ${rows[2]}"
[[ "${rows[3]}" == $'adl_high\t10.0000000000000000\t0.0000000000000000' ]] ||
  die "High-ranked balance mismatch: ${rows[3]}"
[[ "${rows[4]}" == $'adl_liquidated\t0.0000000000000000\t0.0000000000000000' ]] ||
  die "Liquidated balance mismatch: ${rows[4]}"
[[ "${rows[5]}" == $'adl_low\t100.0000000000000000\t5.4760000000000000' ]] ||
  die "Low-ranked balance mismatch: ${rows[5]}"
[[ "${rows[6]}" == $'adl_high\t0.000000000\t0.000000000' ]] ||
  die "High-ranked position mismatch: ${rows[6]}"
[[ "${rows[7]}" == $'adl_low\t0.273800000\t5.476000000' ]] ||
  die "Low-ranked position mismatch: ${rows[7]}"
[[ "${rows[8]}" == $'2.000000000' ]] || die "Cross-tenant position was modified: ${rows[8]}"

foreign_ledger_count="$({
  cat <<SQL
SELECT COUNT(*) FROM dc.dc_adl_ledger
WHERE location='${OTHER_LOCATION}' AND liquidation_order_id='${ORDER_ID}';
SQL
} | mysql_exec)"
[[ "${foreign_ledger_count}" == "0" ]] || die "Cross-tenant ADL ledger was created"

log "PASS: transactional ADL completed, ranking and balances are correct, foreign tenant stayed untouched."
