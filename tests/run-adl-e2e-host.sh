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

# Candidate profitability is evaluated against TradeSvr's live tenant mark,
# not the execution price below.  Use deterministic profitable averages and a
# one-step first candidate so both ranking slots are exercised at any normal
# BTC mark price.
high_short_average="900000"
low_short_average="800000"
foreign_short_average="950000"
liquidated_long_average="$(awk -v price="${REFERENCE_PRICE}" 'BEGIN {printf "%.8f", price + 100}')"
# Keep the deterministic post-fill deficit at 99.048 for any reference price:
# initial balance + (-100 realized PnL) + (-0.06% taker fee) = -99.048.
liquidated_balance="$(awk -v price="${REFERENCE_PRICE}" \
  'BEGIN {printf "%.8f", 0.952 + (price * 0.0006)}')"

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
  AND user_id IN ('adl_liquidated','adl_high','adl_low','adl_foreign',
                  'final_liquidated','final_adl_high','final_adl_foreign','final_maker',
                  'liq_trigger','liq_maker','liq_foreign');
DELETE FROM dc.dc_users_balance WHERE location IN ('${ADL_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('adl_liquidated','adl_high','adl_low','adl_foreign',
                  'final_liquidated','final_adl_high','final_adl_foreign','final_maker',
                  'liq_trigger','liq_maker','liq_foreign');
DELETE FROM dc.dc_insurance_fund WHERE location='${ADL_LOCATION}' AND security_id='BTCUSDT';

INSERT INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('adl_liquidated',${liquidated_balance},1.8,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_high',10,0.001,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_low',100,20,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_foreign',10,10,0,0,NOW(),'ADL_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_orders_position
  (user_id,security_id,symbol,status,position_type,leverage,
   long_position,long_average,long_used_margin,short_position,short_average,short_used_margin,
   long_locked_position,short_locked_position,long_liq_price,short_liq_price,
   update_time,close_by,location)
VALUES
  ('adl_liquidated','BTCUSDT','BTCUSDT',0,'Cross',100,
   1,${liquidated_long_average},1.8,0,0,0,1,0,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
  ('adl_high','BTCUSDT','BTCUSDT',0,'Cross',100,
   0,0,0,0.0001,${high_short_average},0.001,0,0,0,0,NOW(),'ADL_E2E','${ADL_LOCATION}'),
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
{"serverName":"TradeSvr","method":"updateOrder","content":{"ExecType":"Trade","ExecID":"ADL-E2E-EXEC-001","OrdStatus":"Filled","OCType":"ClOSE","OrderID":"${ORDER_ID}","SecurityID":"BTCUSDT","UserID":"adl_liquidated","Side":"Sell","LastQty":"1","LastPx":"${REFERENCE_PRICE}","OrigOrdPrice":"${REFERENCE_PRICE}","LeavesQty":"0","Maker":"false","CloseBy":"liq","Location":"${ADL_LOCATION}","Demo":""}}
JSON

response=""
for attempt in $(seq 1 30); do
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data-binary "@${request_file}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
    die "TradeSvr updateOrder request failed"
  if grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}"; then
    break
  fi
  if grep -Fq 'is not Online' <<<"${response}" || grep -Fq 'SYMBOL_NOTEXIST' <<<"${response}"; then
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
SELECT IF(rank_no=1 AND candidate_user_id='adl_high' AND position_side='SHORT'
          AND ABS(reduced_quantity-0.0001)<0.00000001
          AND ABS(realized_pnl-((900000-reference_price)*0.0001))<0.00000001
          AND ABS(allocated_amount-realized_pnl)<0.00000001,1,0)
FROM dc.dc_adl_ledger
WHERE location='${ADL_LOCATION}' AND liquidation_order_id='${ORDER_ID}' AND rank_no=1;
SELECT IF(l.rank_no=2 AND l.candidate_user_id='adl_low' AND l.position_side='SHORT'
          AND ABS(l.reduced_quantity-0.0001)<0.00000001
          AND ABS(l.realized_pnl-((800000-l.reference_price)*0.0001))<0.00000001
          AND ABS(l.allocated_amount-(99.048-h.allocated_amount))<0.00000001,1,0)
FROM dc.dc_adl_ledger l JOIN dc.dc_adl_ledger h
  ON h.location=l.location AND h.liquidation_order_id=l.liquidation_order_id AND h.rank_no=1
WHERE l.location='${ADL_LOCATION}' AND l.liquidation_order_id='${ORDER_ID}' AND l.rank_no=2;
SELECT IF(ABS(b.balance-10)<0.00000001 AND ABS(b.used_margin)<0.00000001,1,0)
FROM dc.dc_users_balance b
WHERE b.location='${ADL_LOCATION}' AND b.user_id='adl_high';
SELECT IF(ABS(b.balance)<0.00000001 AND ABS(b.used_margin)<0.00000001,1,0)
FROM dc.dc_users_balance b
WHERE b.location='${ADL_LOCATION}' AND b.user_id='adl_liquidated';
SELECT IF(ABS(b.balance-(100+l.realized_pnl-l.allocated_amount))<0.00000001
          AND ABS(b.used_margin-19.998)<0.00000001,1,0)
FROM dc.dc_users_balance b JOIN dc.dc_adl_ledger l
  ON l.location=b.location AND l.candidate_user_id=b.user_id
  AND l.liquidation_order_id='${ORDER_ID}' AND l.rank_no=2
WHERE b.location='${ADL_LOCATION}' AND b.user_id='adl_low';
SELECT IF(ABS(short_position)<0.00000001 AND ABS(short_used_margin)<0.00000001,1,0)
FROM dc.dc_orders_position
WHERE location='${ADL_LOCATION}' AND user_id='adl_high' AND security_id='BTCUSDT';
SELECT IF(ABS(short_position-0.9999)<0.00000001 AND ABS(short_used_margin-19.998)<0.00000001,1,0)
FROM dc.dc_orders_position
WHERE location='${ADL_LOCATION}' AND user_id='adl_low' AND security_id='BTCUSDT';
SELECT IF(ABS(short_position-2)<0.00000001,1,0)
FROM dc.dc_orders_position
WHERE location='${OTHER_LOCATION}' AND user_id='adl_foreign' AND security_id='BTCUSDT';
SQL
} | mysql_exec)"

mapfile -t rows <<<"${result}"
[[ "${#rows[@]}" -eq 9 ]] || die "Unexpected ADL verification row count: ${#rows[@]} (${result})"
[[ "${rows[0]}" == $'COMPLETED\t99.0480000000000000\t0.0000000000000000\t99.0480000000000000\t0.0000000000000000\tCOMPLETED\t2' ]] ||
  die "ADL event/deficit mismatch: ${rows[0]}"
[[ "${rows[1]}" == "1" ]] ||
  die "First-ranked candidate mismatch: ${rows[1]}"
[[ "${rows[2]}" == "1" ]] ||
  die "Second-ranked candidate mismatch: ${rows[2]}"
[[ "${rows[3]}" == "1" ]] ||
  die "High-ranked balance mismatch: ${rows[3]}"
[[ "${rows[4]}" == "1" ]] ||
  die "Liquidated balance mismatch: ${rows[4]}"
[[ "${rows[5]}" == "1" ]] ||
  die "Low-ranked balance mismatch: ${rows[5]}"
[[ "${rows[6]}" == "1" ]] ||
  die "High-ranked position mismatch: ${rows[6]}"
[[ "${rows[7]}" == "1" ]] ||
  die "Low-ranked position mismatch: ${rows[7]}"
[[ "${rows[8]}" == "1" ]] || die "Cross-tenant position was modified: ${rows[8]}"

foreign_ledger_count="$({
  cat <<SQL
SELECT COUNT(*) FROM dc.dc_adl_ledger
WHERE location='${OTHER_LOCATION}' AND liquidation_order_id='${ORDER_ID}';
SQL
} | mysql_exec)"
[[ "${foreign_ledger_count}" == "0" ]] || die "Cross-tenant ADL ledger was created"

log "PASS: transactional ADL completed, ranking and balances are correct, foreign tenant stayed untouched."
