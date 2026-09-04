#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
LIQ_LOCATION="${FINAL_LIQ_E2E_LOCATION:-FINAL_LIQ_V2_E2E}"
OTHER_LOCATION="${FINAL_LIQ_E2E_OTHER_LOCATION:-${LIQ_LOCATION}_FOREIGN}"
SCENARIO="${FINAL_LIQ_E2E_SCENARIO:-mixed}"
LIQ_USER="${FINAL_LIQ_E2E_USER:-final_v2_liquidated}"
MAKER_USER="${FINAL_LIQ_E2E_MAKER:-final_v2_maker}"
ADL_USER="${FINAL_LIQ_E2E_ADL_USER:-final_v2_adl_high}"
FOREIGN_USER="${FINAL_LIQ_E2E_FOREIGN_USER:-final_v2_adl_foreign}"
ADL_AVERAGE="${FINAL_LIQ_E2E_ADL_AVERAGE:-1000000}"
maker_price="60000"
insurance_balance="9"
expected_order_status="Cancelled"
expected_transfer_status="ADL_DONE"
maker_request=""
liq_test_stopped="false"

log() { printf '[final-liq-e2e] %s\n' "$*"; }
die() { printf '[final-liq-e2e] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"
for value in "${LIQ_LOCATION}" "${OTHER_LOCATION}" "${LIQ_USER}" "${MAKER_USER}" \
  "${ADL_USER}" "${FOREIGN_USER}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LIQ_LOCATION}" != "${OTHER_LOCATION}" ]] || die "Liquidation locations must differ"
case "${SCENARIO}" in
  mixed) ;;
  full_fill)
    maker_price="90000"
    expected_order_status="Filled"
    expected_transfer_status=""
    ;;
  full_insurance)
    insurance_balance="18"
    expected_transfer_status="INSURANCE_TAKEOVER"
    ;;
  *) die "FINAL_LIQ_E2E_SCENARIO must be mixed, full_fill or full_insurance" ;;
esac
[[ "${ADL_AVERAGE}" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
  die "FINAL_LIQ_E2E_ADL_AVERAGE must be a nonnegative number"

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

password_hash="$(printf '%s' "${E2E_PASSWORD}" | sha256sum | awk '{print $1}')"

login_user() {
  local user="$1" request response token
  request="$(mktemp)"
  chmod 0600 "${request}"
  printf '{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"%s","user_name":"%s","password":"%s","method":"login","client_type":"WEB","cid":"FINAL_LIQ_E2E_%s","Location":"%s"}}\n' \
    "${user}" "${user}" "${E2E_PASSWORD}" "${user}" "${LIQ_LOCATION}" >"${request}"
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
    --data-binary "@${request}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" || {
      rm -f "${request}"
      die "Could not authenticate final-liquidation liquidity user ${user}"
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
  die "Final-liquidation maker username belongs to another identity or location"

log "Stopping LiqSvr while the deterministic final-liquidation fixture is loaded."
docker stop dc-saas-liqsvr >/dev/null
liq_test_stopped="true"

log "Preparing final-liquidation, insurance and ADL accounts in ${LIQ_LOCATION}."
{
  cat <<SQL
START TRANSACTION;
-- The full acceptance suite reuses one location by design.  A completed run of
-- run-adl-e2e-host.sh intentionally leaves its reduced candidate positions in
-- place as evidence; remove those named test fixtures before constructing this
-- single-candidate final-liquidation scenario so repeated suites are isolated.
DELETE FROM dc.dc_adl_execution_v2 WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND (liquidated_user_id='${LIQ_USER}' OR candidate_user_id IN ('${ADL_USER}','${FOREIGN_USER}'));
DELETE FROM dc.dc_bankruptcy_transfer WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id='${LIQ_USER}';
DELETE FROM dc.dc_insurance_position WHERE location='${LIQ_LOCATION}' AND security_id='BTCUSDT';
DELETE FROM dc.dc_users_posting WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${ADL_USER}','${FOREIGN_USER}',
                  'adl_liquidated','adl_high','adl_low','adl_foreign');
DELETE FROM dc.dc_adl_ledger WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND (liquidated_user_id IN ('${LIQ_USER}','adl_liquidated')
       OR candidate_user_id IN ('${ADL_USER}','${FOREIGN_USER}','adl_high','adl_low','adl_foreign'));
DELETE FROM dc.dc_adl_event WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}') AND user_id='${LIQ_USER}';
DELETE FROM dc.dc_liquidation_deficit WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id='${LIQ_USER}';
DELETE FROM dc.dc_order_idempotency WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${ADL_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_orders_execorders WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${ADL_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_orders WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${ADL_USER}','${FOREIGN_USER}');
DELETE FROM dc.dc_orders_position WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${ADL_USER}','${FOREIGN_USER}',
                  'adl_liquidated','adl_high','adl_low','adl_foreign');
DELETE FROM dc.dc_users_balance WHERE location IN ('${LIQ_LOCATION}','${OTHER_LOCATION}')
  AND user_id IN ('${LIQ_USER}','${MAKER_USER}','${ADL_USER}','${FOREIGN_USER}',
                  'adl_liquidated','adl_high','adl_low','adl_foreign');
DELETE FROM dc.dc_insurance_fund WHERE location='${LIQ_LOCATION}' AND security_id='BTCUSDT';

INSERT INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${LIQ_USER}',2,0.2,0,0,NOW(),'FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${MAKER_USER}',100000,0,0,0,NOW(),'FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${ADL_USER}',10,0.7,0,0,NOW(),'FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}',10,0.7,0,0,NOW(),'FINAL_LIQ_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_users
  (user_id,user_name,name,password,user_type,enable,create_time,update_time,
   enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES
  ('${MAKER_USER}','${MAKER_USER}','Final Liquidation Maker','${password_hash}','1','1',NOW(),NOW(),
   '1','1','1','FINAL_LIQ_E2E','${LIQ_LOCATION}')
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
   0.0002,100000,0.2,0,0,0,0,0,999999,0,NOW(),'FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${ADL_USER}','BTCUSDT','BTCUSDT',0,'Cross',100,
   0,0,0,0.001,${ADL_AVERAGE},0.7,0,0,0,0,NOW(),'FINAL_LIQ_E2E','${LIQ_LOCATION}'),
  ('${FOREIGN_USER}','BTCUSDT','BTCUSDT',0,'Cross',100,
   0,0,0,0.001,70000,0.7,0,0,0,0,NOW(),'FINAL_LIQ_E2E','${OTHER_LOCATION}');

INSERT INTO dc.dc_insurance_fund(location,security_id,balance,update_time)
VALUES('${LIQ_LOCATION}','BTCUSDT',${insurance_balance},NOW());
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
{"serverName":"OrderSvr","method":"placeOrder","content":{"OCType":"OPEN","OrderQty":"0.0002","OrdType":"Limit","ClOrdID":"FINAL-LIQ-MAKER-$(date +%s%N)","Terminal":"API","AlgoName":"cross","Side":"Buy","Price":"${maker_price}","UserID":"${MAKER_USER}","MarketIndicator":"4","TimeInForce":"GTC","SecurityID":"BTCUSDT","Location":"${LIQ_LOCATION}"}}
JSON
maker_response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' -H "sessionId: ${maker_session}" \
  --data-binary "@${maker_request}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" ||
  die "Could not place final-liquidation liquidity order"
grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${maker_response}" ||
  die "Liquidity order was rejected: ${maker_response}"

maker_open="0"
for _ in $(seq 1 30); do
  maker_open="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LIQ_LOCATION}' AND user_id='${MAKER_USER}'
  AND security_id='BTCUSDT' AND ord_status='New' AND leaves_qty=0.0002;
SQL
  } | mysql_exec dc)"
  [[ "${maker_open}" == "1" ]] && break
  sleep 1
done
[[ "${maker_open}" == "1" ]] || die "Liquidity order did not rest in the order book"

log "Starting LiqSvr to trigger bankruptcy-bounded final liquidation through OrderSvr."
docker start dc-saas-liqsvr >/dev/null
liq_test_stopped="false"

liquidation_order_id=""
for _ in $(seq 1 90); do
  liquidation_order_id="$({
    cat <<SQL
SELECT order_id FROM dc.dc_orders WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}'
  AND security_id='BTCUSDT' AND UPPER(oc_type)='CLOSE' AND reduce_only=1
  AND ord_type='Limit' AND timeinforce='IOC' AND close_by='liq_v2' AND ord_status='${expected_order_status}'
ORDER BY transact_time DESC LIMIT 1;
SQL
  } | mysql_exec dc)"
  [[ -n "${liquidation_order_id}" ]] && break
  sleep 2
done
if [[ -z "${liquidation_order_id}" ]]; then
  docker logs --tail 200 dc-saas-liqsvr >&2 || true
  docker logs --tail 200 dc-saas-tradesvr >&2 || true
  die "LiqSvr did not create a bankruptcy-bounded final reduce-only Limit/IOC order"
fi

if [[ -n "${expected_transfer_status}" ]]; then
  completed="0"
  for _ in $(seq 1 60); do
    completed="$(mysql_exec -e "SELECT COUNT(*) FROM dc.dc_bankruptcy_transfer
      WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}'
        AND liquidation_side='Sell' AND status='${expected_transfer_status}';" dc)"
    [[ "${completed}" == "1" ]] && break
    sleep 2
  done
  [[ "${completed}" == "1" ]] || {
    docker logs --tail 200 dc-saas-liqsvr >&2 || true
    docker logs --tail 200 dc-saas-tradesvr >&2 || true
    die "Bankruptcy takeover did not reach ${expected_transfer_status}"
  }
fi

log "Verifying ${SCENARIO} final-liquidation outcome for ${liquidation_order_id}."
if [[ "${SCENARIO}" == "full_fill" ]]; then
  verification="$({
    cat <<SQL
SELECT IF(ABS(COALESCE(SUM(last_qty),0)-0.0002)<0.00000001,1,0)
FROM dc.dc_orders_execorders
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND order_id='${liquidation_order_id}'
  AND UPPER(oc_type)='CLOSE' AND exec_type='Trade';
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_bankruptcy_transfer
WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}';
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_insurance_position
WHERE location='${LIQ_LOCATION}' AND security_id='BTCUSDT';
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_adl_execution_v2
WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}';
SELECT IF(ABS(p.long_position)<0.00000001 AND ABS(p.long_used_margin)<0.00000001
          AND ABS(b.balance)<0.00000001 AND ABS(b.used_margin)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LIQ_LOCATION}' AND p.user_id='${LIQ_USER}' AND p.security_id='BTCUSDT';
SELECT IF(ABS(balance-${insurance_balance})<0.00000001,1,0) FROM dc.dc_insurance_fund
WHERE location='${LIQ_LOCATION}' AND security_id='BTCUSDT';
SQL
  } | mysql_exec dc)"
  mapfile -t checks <<<"${verification}"
  [[ "${#checks[@]}" -eq 6 ]] || die "Unexpected full-fill verification output: ${verification}"
  for index in "${!checks[@]}"; do
    [[ "${checks[${index}]}" == "1" ]] ||
      die "Full-fill verification check $((index + 1)) failed for ${liquidation_order_id}"
  done
  log "PASS: final IOC/Limit fully filled at the bankruptcy bound without insurance or ADL."
  exit 0
fi

if [[ "${SCENARIO}" == "full_insurance" ]]; then
  verification="$({
    cat <<SQL
SELECT IF(t.status='INSURANCE_TAKEOVER' AND ABS(t.requested_quantity-0.0002)<0.00000001
          AND ABS(t.insurance_quantity-0.0002)<0.00000001 AND ABS(t.adl_quantity)<0.00000001
          AND ABS(t.insurance_notional-(t.bankruptcy_price*0.0002))<0.00000001
          AND ABS(t.settlement_pnl-((t.bankruptcy_price-100000)*0.0002))<0.00000001,1,0)
FROM dc.dc_bankruptcy_transfer t
WHERE t.location='${LIQ_LOCATION}' AND t.liquidation_order_id='${liquidation_order_id}'
  AND t.liquidation_side='Sell';
SELECT IF(ABS(f.balance)<0.00000001 AND ABS(p.quantity-0.0002)<0.00000001
          AND ABS(p.average_price-t.bankruptcy_price)<0.00000001
          AND ABS(p.reserved_notional-t.insurance_notional)<0.00000001,1,0)
FROM dc.dc_insurance_fund f JOIN dc.dc_insurance_position p
  ON p.location=f.location AND p.security_id=f.security_id AND p.position_side='LONG'
JOIN dc.dc_bankruptcy_transfer t
  ON t.location=f.location AND t.security_id=f.security_id
  AND t.liquidation_order_id='${liquidation_order_id}'
WHERE f.location='${LIQ_LOCATION}' AND f.security_id='BTCUSDT';
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_adl_execution_v2
WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}';
SELECT IF(ABS(p.long_position)<0.00000001 AND ABS(p.long_used_margin)<0.00000001
          AND ABS(b.balance)<0.00000001 AND ABS(b.used_margin)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LIQ_LOCATION}' AND p.user_id='${LIQ_USER}' AND p.security_id='BTCUSDT';
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_orders_execorders
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND order_id='${liquidation_order_id}'
  AND UPPER(oc_type)='CLOSE';
SELECT IF(COUNT(*)=1,1,0) FROM dc.dc_users_posting
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND source_id='${liquidation_order_id}'
  AND source='BankruptcyTransfer';
SQL
  } | mysql_exec dc)"
  mapfile -t checks <<<"${verification}"
  [[ "${#checks[@]}" -eq 6 ]] || die "Unexpected full-insurance verification output: ${verification}"
  for index in "${!checks[@]}"; do
    [[ "${checks[${index}]}" == "1" ]] ||
      die "Full-insurance verification check $((index + 1)) failed for ${liquidation_order_id}"
  done
  log "PASS: insurance fund fully absorbed the bankrupt residual without ADL."
  exit 0
fi

verification="$({
  cat <<SQL
SELECT IF(t.status='ADL_DONE' AND ABS(t.requested_quantity-0.0002)<0.00000001
          AND ABS(t.insurance_quantity-0.0001)<0.00000001
          AND ABS(t.adl_quantity-0.0001)<0.00000001
          AND ABS(t.insurance_notional-(t.bankruptcy_price*0.0001))<0.00000001
          AND ABS(t.settlement_pnl-((t.bankruptcy_price-100000)*0.0002))<0.00000001,1,0)
FROM dc.dc_bankruptcy_transfer t
WHERE t.location='${LIQ_LOCATION}' AND t.liquidation_order_id='${liquidation_order_id}'
  AND t.liquidation_side='Sell';
SELECT IF(rank_no=1 AND candidate_user_id='${ADL_USER}' AND candidate_position_side='SHORT'
          AND ABS(quantity-0.0001)<0.00000001
          AND ABS(realized_pnl-((${ADL_AVERAGE}-execution_price)*0.0001))<0.00000001,1,0)
FROM dc.dc_adl_execution_v2
WHERE location='${LIQ_LOCATION}' AND liquidation_order_id='${liquidation_order_id}';
SELECT IF(ABS(p.long_position)<0.00000001 AND ABS(p.long_used_margin)<0.00000001
          AND ABS(b.balance)<0.00000001 AND ABS(b.used_margin)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LIQ_LOCATION}' AND p.user_id='${LIQ_USER}' AND p.security_id='BTCUSDT';
SELECT IF(ABS(p.short_position-0.0009)<0.00000001 AND ABS(p.short_used_margin-0.63)<0.00000001
          AND ABS(b.balance-(10+l.realized_pnl))<0.00000001
          AND ABS(b.used_margin-0.63)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
JOIN dc.dc_adl_execution_v2 l
  ON l.location=p.location AND l.candidate_user_id=p.user_id
  AND l.liquidation_order_id='${liquidation_order_id}'
WHERE p.location='${LIQ_LOCATION}' AND p.user_id='${ADL_USER}' AND p.security_id='BTCUSDT';
SELECT IF(ABS(f.balance)<0.00000001 AND ABS(p.quantity-0.0001)<0.00000001
          AND ABS(p.average_price-t.bankruptcy_price)<0.00000001
          AND ABS(p.reserved_notional-t.insurance_notional)<0.00000001,1,0)
FROM dc.dc_insurance_fund f JOIN dc.dc_insurance_position p
  ON p.location=f.location AND p.security_id=f.security_id AND p.position_side='LONG'
JOIN dc.dc_bankruptcy_transfer t
  ON t.location=f.location AND t.security_id=f.security_id
  AND t.liquidation_order_id='${liquidation_order_id}'
WHERE f.location='${LIQ_LOCATION}' AND f.security_id='BTCUSDT';
SELECT IF(ABS(p.short_position-0.001)<0.00000001 AND ABS(p.short_used_margin-0.7)<0.00000001
          AND ABS(b.balance-10)<0.00000001 AND ABS(b.used_margin-0.7)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${OTHER_LOCATION}' AND p.user_id='${FOREIGN_USER}' AND p.security_id='BTCUSDT';
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_orders_execorders
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND order_id='${liquidation_order_id}'
  AND UPPER(oc_type)='CLOSE';
SELECT IF(COUNT(*)=1,1,0) FROM dc.dc_users_posting
WHERE location='${LIQ_LOCATION}' AND user_id='${LIQ_USER}' AND source_id='${liquidation_order_id}'
  AND source='BankruptcyTransfer';
SQL
} | mysql_exec dc)"
mapfile -t checks <<<"${verification}"
[[ "${#checks[@]}" -eq 8 ]] || die "Unexpected final-liquidation verification output: ${verification}"
for index in "${!checks[@]}"; do
  [[ "${checks[${index}]}" == "1" ]] ||
    die "Final-liquidation verification check $((index + 1)) failed for ${liquidation_order_id}"
done

log "PASS: final IOC/Limit respected bankruptcy price and residual risk completed transactional insurance/ADL v2."
