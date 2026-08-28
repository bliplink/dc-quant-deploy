#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
RULE_LOCATION="${RULE_E2E_LOCATION:-CORE_E2E}"
MAKER_ONE="${RULE_E2E_MAKER_ONE:-rulemaker1}"
MAKER_TWO="${RULE_E2E_MAKER_TWO:-rulemaker2}"
TAKER="${RULE_E2E_TAKER:-ruletaker}"
SELF_USER="${RULE_E2E_SELF_USER:-ruleself}"
RUN_ID="${RULE_E2E_RUN_ID:-$(date +%Y%m%d%H%M%S)}"

log() { printf '[rules-e2e] %s\n' "$*"; }
die() { printf '[rules-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
for value in "${RULE_LOCATION}" "${MAKER_ONE}" "${MAKER_TWO}" "${TAKER}" "${SELF_USER}" "${RUN_ID}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

liq_was_running="$(docker inspect --format '{{.State.Running}}' dc-saas-liqsvr 2>/dev/null || true)"
restore_liqsvr() {
  if [[ "${liq_was_running}" == "true" ]]; then
    docker start dc-saas-liqsvr >/dev/null 2>&1 || true
  fi
}
trap restore_liqsvr EXIT
if [[ "${liq_was_running}" == "true" ]]; then
  log "Pausing LiqSvr so background liquidation cannot consume deterministic rule-test liquidity."
  docker stop dc-saas-liqsvr >/dev/null
fi

mysql_exec() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -N "$@"
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
      --data "{\"serverName\":\"${server}\",\"method\":\"__rules_readiness__\",\"content\":{}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && ! grep -Fq 'is not Online' <<<"${response}"; then return 0; fi
    if (( $(date +%s) - start >= 120 )); then die "${server} did not become routable"; fi
    sleep 2
  done
}

API_RESPONSE=""
api() {
  local method="$1" content="$2" request
  request="$(mktemp)"
  printf '{"serverName":"OrderSvr","method":"%s","content":%s}\n' "${method}" "${content}" >"${request}"
  API_RESPONSE="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data-binary "@${request}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" || {
      rm -f "${request}"
      die "${method} request failed"
    }
  rm -f "${request}"
}

place() {
  local user="$1" side="$2" qty="$3" price="$4" tif="$5" clid="$6"
  local ord_type="${7:-Limit}" oc_type="${8:-OPEN}" reduce_only="${9:-false}"
  api placeOrder "{\"OCType\":\"${oc_type}\",\"OrderQty\":\"${qty}\",\"OrdType\":\"${ord_type}\",\"ClOrdID\":\"${clid}\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"${side}\",\"Price\":\"${price}\",\"UserID\":\"${user}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"${tif}\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"${reduce_only}\",\"Location\":\"${RULE_LOCATION}\"}"
}

assert_success() {
  grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${API_RESPONSE}" ||
    die "Expected success, got: ${API_RESPONSE}"
}

assert_rejected() {
  if grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${API_RESPONSE}"; then
    die "Expected rejection, got: ${API_RESPONSE}"
  fi
}

response_order_id() {
  sed -n 's/.*"info1"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' <<<"${API_RESPONSE}"
}

wait_order() {
  local clid="$1" status="$2" count="0"
  for _ in $(seq 1 60); do
    count="$({
      cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='${clid}' AND ord_status='${status}';
SQL
    } | mysql_exec dc)"
    [[ "${count}" == "1" ]] && return 0
    sleep 1
  done
  die "Order ${clid} did not reach ${status}"
}

log "Preparing deterministic rule-test accounts in ${RULE_LOCATION}."
{
  cat <<SQL
START TRANSACTION;
DELETE FROM dc.dc_order_idempotency WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
DELETE FROM dc.dc_orders_execorders WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
DELETE FROM dc.dc_orders WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
DELETE FROM dc.dc_orders_position WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
DELETE FROM dc.dc_users_posting WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
DELETE FROM dc.dc_users_balance WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
DELETE FROM dc.dc_users_symbol_config WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}');
INSERT INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${MAKER_ONE}',100000,0,0,0,NOW(),'RULE_E2E','${RULE_LOCATION}'),
  ('${MAKER_TWO}',100000,0,0,0,NOW(),'RULE_E2E','${RULE_LOCATION}'),
  ('${TAKER}',100000,0,0,0,NOW(),'RULE_E2E','${RULE_LOCATION}'),
  ('${SELF_USER}',100000,0,0,0,NOW(),'RULE_E2E','${RULE_LOCATION}');
INSERT INTO dc.dc_users_symbol_config
  (user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES
  ('${MAKER_ONE}','BTCUSDT','BTCUSDT',100,'Cross',NOW(),'RULE_E2E','${RULE_LOCATION}','4'),
  ('${MAKER_TWO}','BTCUSDT','BTCUSDT',100,'Cross',NOW(),'RULE_E2E','${RULE_LOCATION}','4'),
  ('${TAKER}','BTCUSDT','BTCUSDT',100,'Cross',NOW(),'RULE_E2E','${RULE_LOCATION}','4'),
  ('${SELF_USER}','BTCUSDT','BTCUSDT',100,'Cross',NOW(),'RULE_E2E','${RULE_LOCATION}','4');
COMMIT;
SQL
} | mysql_exec dc

docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
docker restart dc-saas-gateway >/dev/null
wait_for_route OrderSvr
wait_for_route TDSvr

log "Checking synchronous input and symbol filters."
place "${TAKER}" Buy 0.0001 60000.05 GTC "RULE-${RUN_ID}-REJECT-TICK"; assert_rejected
place "${TAKER}" Buy 0.00015 60000 GTC "RULE-${RUN_ID}-REJECT-STEP"; assert_rejected
place "${TAKER}" Buy 0.00001 60000 GTC "RULE-${RUN_ID}-REJECT-MINQTY"; assert_rejected
place "${TAKER}" Buy 10.0001 60000 GTC "RULE-${RUN_ID}-REJECT-MAXQTY"; assert_rejected
place "${TAKER}" Buy 0.0001 10000 GTC "RULE-${RUN_ID}-REJECT-NOTIONAL"; assert_rejected
place "${TAKER}" Buy 0.0001 60000 GTT "RULE-${RUN_ID}-REJECT-TIF"; assert_rejected
place "${TAKER}" Buy 0.0001 60000 GTC "RULE-${RUN_ID}-REJECT-MARKET-TIF" Market; assert_rejected
place "${TAKER}" Buy 0.0001 60000 PO "RULE-${RUN_ID}-REJECT-MARKET-PO" Market; assert_rejected
place "${TAKER}" Buy 0.0001 60000 GTC "RULE-${RUN_ID}-REJECT-REDUCE-OPEN" Limit OPEN true; assert_rejected
rejected_rows="$({
  cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id LIKE 'RULE-${RUN_ID}-REJECT-%';
SQL
} | mysql_exec dc)"
[[ "${rejected_rows}" == "0" ]] || die "Rejected inputs created persisted orders"

log "Checking FOK all-or-none and IOC partial-fill semantics."
place "${MAKER_ONE}" Sell 0.0002 60000 GTC "RULE-${RUN_ID}-FOK-MAKER"; assert_success
wait_order "RULE-${RUN_ID}-FOK-MAKER" New
place "${TAKER}" Buy 0.0003 60000 FOK "RULE-${RUN_ID}-FOK-TAKER"; assert_success
wait_order "RULE-${RUN_ID}-FOK-TAKER" Cancelled
fok_check="$({
  cat <<SQL
SELECT IF((SELECT cum_qty FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-FOK-TAKER')=0
 AND (SELECT leaves_qty FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-FOK-MAKER')=0.0002,1,0);
SQL
} | mysql_exec dc)"
[[ "${fok_check}" == "1" ]] || die "FOK generated a partial execution or consumed maker liquidity"

place "${TAKER}" Buy 0.0003 60000 IOC "RULE-${RUN_ID}-IOC-TAKER"; assert_success
wait_order "RULE-${RUN_ID}-IOC-TAKER" Cancelled
ioc_check="$({
  cat <<SQL
SELECT IF(cum_qty=0.0002 AND leaves_qty=0.0001,1,0) FROM dc.dc_orders
WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-IOC-TAKER';
SQL
} | mysql_exec dc)"
[[ "${ioc_check}" == "1" ]] || die "IOC did not fill available quantity and cancel its remainder"

log "Checking Post Only and price-time priority."
place "${MAKER_ONE}" Sell 0.0001 60100 GTC "RULE-${RUN_ID}-PO-MAKER"; assert_success
wait_order "RULE-${RUN_ID}-PO-MAKER" New
place "${TAKER}" Buy 0.0001 60100 PO "RULE-${RUN_ID}-PO-TAKER"; assert_success
wait_order "RULE-${RUN_ID}-PO-TAKER" Cancelled
po_check="$({
  cat <<SQL
SELECT IF((SELECT ord_status FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-PO-MAKER')='New'
 AND (SELECT cum_qty FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-PO-TAKER')=0,1,0);
SQL
} | mysql_exec dc)"
[[ "${po_check}" == "1" ]] || die "Post Only consumed resting liquidity"
po_maker_id="$({
  cat <<SQL
SELECT order_id FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-PO-MAKER' LIMIT 1;
SQL
} | mysql_exec dc)"
api cancelOrder "{\"UserID\":\"${MAKER_ONE}\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\",\"OrderID\":\"${po_maker_id}\",\"AlgoName\":\"cross\",\"Location\":\"${RULE_LOCATION}\"}"
assert_success
wait_order "RULE-${RUN_ID}-PO-MAKER" Cancelled

place "${MAKER_ONE}" Sell 0.0001 60200 GTC "RULE-${RUN_ID}-FIFO-ONE"; assert_success
wait_order "RULE-${RUN_ID}-FIFO-ONE" New
place "${MAKER_TWO}" Sell 0.0001 60200 GTC "RULE-${RUN_ID}-FIFO-TWO"; assert_success
wait_order "RULE-${RUN_ID}-FIFO-TWO" New
place "${TAKER}" Buy 0.0001 60200 GTC "RULE-${RUN_ID}-FIFO-TAKER"; assert_success
wait_order "RULE-${RUN_ID}-FIFO-TAKER" Filled
fifo_check="$({
  cat <<SQL
SELECT IF((SELECT ord_status FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-FIFO-ONE')='Filled'
 AND (SELECT ord_status FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-FIFO-TWO')='New',1,0);
SQL
} | mysql_exec dc)"
[[ "${fifo_check}" == "1" ]] || die "Same-price orders did not follow time priority"

# FIFO-TWO is intentionally left resting by the priority assertion. Remove it
# before the STP case so the self-cross is the best (and only) eligible match.
fifo_two_id="$({
  cat <<SQL
SELECT order_id FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-FIFO-TWO' LIMIT 1;
SQL
} | mysql_exec dc)"
[[ -n "${fifo_two_id}" ]] || die "Could not resolve remaining FIFO order"
api cancelOrder "{\"UserID\":\"${MAKER_TWO}\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\",\"OrderID\":\"${fifo_two_id}\",\"AlgoName\":\"cross\",\"Location\":\"${RULE_LOCATION}\"}"
assert_success
wait_order "RULE-${RUN_ID}-FIFO-TWO" Cancelled

log "Checking default Cancel Taker self-trade prevention."
place "${SELF_USER}" Sell 0.0001 60300 GTC "RULE-${RUN_ID}-STP-MAKER"; assert_success
wait_order "RULE-${RUN_ID}-STP-MAKER" New
place "${SELF_USER}" Buy 0.0001 60300 GTC "RULE-${RUN_ID}-STP-TAKER"; assert_success
wait_order "RULE-${RUN_ID}-STP-TAKER" Cancelled
stp_check="$({
  cat <<SQL
SELECT IF((SELECT ord_status FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-STP-MAKER')='New'
 AND (SELECT cum_qty FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-STP-TAKER')=0,1,0);
SQL
} | mysql_exec dc)"
[[ "${stp_check}" == "1" ]] || die "Self-trade prevention allowed an execution"

log "Checking client-order idempotency and conflict rejection."
idem_clid="RULE-${RUN_ID}-IDEMPOTENT"
place "${MAKER_TWO}" Buy 0.0001 50000 GTC "${idem_clid}"; assert_success
idem_order_one="$(response_order_id)"
[[ -n "${idem_order_one}" ]] || die "First idempotent request returned no order ID"
place "${MAKER_TWO}" Buy 0.0001 50000 GTC "${idem_clid}"; assert_success
idem_order_two="$(response_order_id)"
[[ "${idem_order_one}" == "${idem_order_two}" ]] || die "Identical idempotent requests returned different order IDs"
place "${MAKER_TWO}" Buy 0.0001 49999.9 GTC "${idem_clid}"; assert_rejected
idem_count="$({
  cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND user_id='${MAKER_TWO}' AND clord_id='${idem_clid}';
SQL
} | mysql_exec dc)"
[[ "${idem_count}" == "1" ]] || die "Idempotent retry persisted duplicate orders"

log "Checking atomic cancel-replace and identity-bound batch cancel."
original_clid="RULE-${RUN_ID}-REPLACE-OLD"
place "${MAKER_TWO}" Sell 0.0001 80000 GTC "${original_clid}"; assert_success
original_id="$(response_order_id)"
wait_order "${original_clid}" New
replacement_clid="RULE-${RUN_ID}-REPLACE-NEW"
api replaceOrder "{\"RefOrderID\":\"${original_id}\",\"OCType\":\"OPEN\",\"OrderQty\":\"0.0002\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${replacement_clid}\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"Sell\",\"Price\":\"79900\",\"UserID\":\"${MAKER_TWO}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"false\",\"Location\":\"${RULE_LOCATION}\"}"
assert_success
wait_order "${original_clid}" Cancelled
wait_order "${replacement_clid}" New

place "${MAKER_TWO}" Sell 0.0001 81000 GTC "RULE-${RUN_ID}-BATCH-ONE"; assert_success
batch_one="$(response_order_id)"; wait_order "RULE-${RUN_ID}-BATCH-ONE" New
place "${MAKER_TWO}" Sell 0.0001 82000 GTC "RULE-${RUN_ID}-BATCH-TWO"; assert_success
batch_two="$(response_order_id)"; wait_order "RULE-${RUN_ID}-BATCH-TWO" New
api cancelBatchOrder "{\"location\":\"${RULE_LOCATION}\",\"userID\":\"${MAKER_TWO}\",\"securityID\":\"BTCUSDT\",\"algoName\":\"cross\",\"orderIDs\":[\"${batch_one}\",\"${batch_two}\"]}"
assert_success
wait_order "RULE-${RUN_ID}-BATCH-ONE" Cancelled
wait_order "RULE-${RUN_ID}-BATCH-TWO" Cancelled

foreign_id="$({
  cat <<SQL
SELECT order_id FROM dc.dc_orders WHERE location='${RULE_LOCATION}' AND clord_id='RULE-${RUN_ID}-STP-MAKER' LIMIT 1;
SQL
} | mysql_exec dc)"
[[ -n "${foreign_id}" ]] || die "Could not resolve another user's order for batch-cancel isolation"
api cancelBatchOrder "{\"location\":\"${RULE_LOCATION}\",\"userID\":\"${MAKER_TWO}\",\"securityID\":\"BTCUSDT\",\"algoName\":\"cross\",\"orderIDs\":[\"${foreign_id}\"]}"
assert_success
wait_order "RULE-${RUN_ID}-STP-MAKER" New

log "Cancelling remaining orders and verifying no active-order or frozen-fund residue."
for user in "${MAKER_ONE}" "${MAKER_TWO}" "${TAKER}" "${SELF_USER}"; do
  api cancelAllOrder "{\"UserID\":\"${user}\",\"SecurityID\":\"BTCUSDT\",\"MarketIndicator\":\"4\",\"AlgoName\":\"cross\",\"Location\":\"${RULE_LOCATION}\"}"
  assert_success
done

for _ in $(seq 1 60); do
  active="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${RULE_LOCATION}'
  AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}')
  AND ord_status IN ('New','Partially_Filled');
SQL
  } | mysql_exec dc)"
  [[ "${active}" == "0" ]] && break
  sleep 1
done
[[ "${active:-1}" == "0" ]] || die "Active orders remained after mass cancel"

api placeOrder "{\"OCType\":\"ClOSE\",\"OrderQty\":\"0.0003\",\"OrdType\":\"Limit\",\"ClOrdID\":\"RULE-${RUN_ID}-CLOSE-SHORT\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"Buy\",\"PositionSide\":\"Short\",\"Price\":\"60000\",\"UserID\":\"${MAKER_ONE}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"true\",\"Location\":\"${RULE_LOCATION}\"}"
assert_success
wait_order "RULE-${RUN_ID}-CLOSE-SHORT" New
api placeOrder "{\"OCType\":\"ClOSE\",\"OrderQty\":\"0.0003\",\"OrdType\":\"Limit\",\"ClOrdID\":\"RULE-${RUN_ID}-CLOSE-LONG\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"Sell\",\"PositionSide\":\"Long\",\"Price\":\"60000\",\"UserID\":\"${TAKER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"true\",\"Location\":\"${RULE_LOCATION}\"}"
assert_success
wait_order "RULE-${RUN_ID}-CLOSE-SHORT" Filled
wait_order "RULE-${RUN_ID}-CLOSE-LONG" Filled

funds_ok="$({
  cat <<SQL
SELECT IF(COUNT(*)=4,1,0) FROM dc.dc_users_balance
WHERE location='${RULE_LOCATION}' AND user_id IN ('${MAKER_ONE}','${MAKER_TWO}','${TAKER}','${SELF_USER}')
  AND ABS(freezed_margin)<0.00000001 AND ABS(freezed_commission)<0.00000001 AND ABS(used_margin)<0.00000001;
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_orders_execorders e
JOIN dc.dc_orders o ON o.location=e.location AND o.order_id=e.order_id AND o.user_id=e.user_id
WHERE e.location='${RULE_LOCATION}' AND o.clord_id LIKE 'RULE-${RUN_ID}-%'
  AND o.timeinforce IN ('FOK','PO') AND o.cum_qty=0;
SELECT IF(COUNT(*)=2,1,0) FROM dc.dc_orders_position
WHERE location='${RULE_LOCATION}' AND user_id IN ('${MAKER_ONE}','${TAKER}')
  AND ABS(long_position)<0.00000001 AND ABS(short_position)<0.00000001
  AND ABS(long_used_margin)<0.00000001 AND ABS(short_used_margin)<0.00000001;
SQL
} | mysql_exec dc)"
[[ "${funds_ok}" == $'1\n1\n1' ]] || die "Final rule-test accounting checks failed: ${funds_ok}"

log "PASS: symbol filters, TIF, Post Only, FIFO, STP, idempotency, replace, batch and mass cancel rules succeeded."
