#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
LOAD_LOCATION="${LOAD_LOCATION:-CORE_E2E}"
LOAD_MAKER="${LOAD_MAKER:-stressmaker}"
LOAD_TAKER="${LOAD_TAKER:-stresstaker}"
LOAD_ORDERS="${LOAD_ORDERS:-1000}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-16}"
LOAD_RUN_ID="${LOAD_RUN_ID:-$(date +%Y%m%d%H%M%S)}"
LOAD_RUNNER_NAME="${LOAD_RUNNER_NAME:-dc-saas-web-e2e-runner}"

log() { printf '[core-stress] %s\n' "$*"; }
die() { printf '[core-stress] ERROR: %s\n' "$*" >&2; exit 1; }
safe_identifier() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
for value in "${LOAD_LOCATION}" "${LOAD_MAKER}" "${LOAD_TAKER}" "${LOAD_RUN_ID}"; do
  safe_identifier "${value}" || die "Unsupported identifier: ${value}"
done
[[ "${LOAD_ORDERS}" =~ ^[1-9][0-9]*$ ]] || die "LOAD_ORDERS must be a positive integer"
[[ "${LOAD_CONCURRENCY}" =~ ^[1-9][0-9]*$ ]] || die "LOAD_CONCURRENCY must be a positive integer"
[[ "${LOAD_MAKER}" != "${LOAD_TAKER}" ]] || die "Load users must differ"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

liq_was_running="$(docker inspect --format '{{.State.Running}}' dc-saas-liqsvr 2>/dev/null || true)"
restore_liqsvr() {
  if [[ "${liq_was_running}" == "true" ]]; then
    timeout 120 docker start dc-saas-liqsvr >/dev/null 2>&1 || true
  fi
}
trap restore_liqsvr EXIT
if [[ "${liq_was_running}" == "true" ]]; then
  log "Pausing LiqSvr so background liquidation cannot alter load-test order flow."
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
      --data "{\"serverName\":\"${server}\",\"method\":\"__load_readiness__\",\"content\":{}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && ! grep -Fq 'is not Online' <<<"${response}"; then return 0; fi
    if (( $(date +%s) - start >= 120 )); then die "${server} did not become routable"; fi
    sleep 2
  done
}

api_order() {
  local content="$1" request response
  request="$(mktemp)"
  printf '{"serverName":"OrderSvr","method":"placeOrder","content":%s}\n' "${content}" >"${request}"
  response="$(curl -fsS --max-time 30 -H 'Content-Type: application/json' --data-binary "@${request}" \
    "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/")" || {
      rm -f "${request}"
      die "Close-order API request failed"
    }
  rm -f "${request}"
  grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}" || die "Close order rejected: ${response}"
}

log "Preparing isolated load accounts in ${LOAD_LOCATION}."
{
  cat <<SQL
START TRANSACTION;
DELETE FROM dc.dc_order_idempotency WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
DELETE FROM dc.dc_orders_execorders WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
DELETE FROM dc.dc_orders WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
DELETE FROM dc.dc_orders_position WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
DELETE FROM dc.dc_users_posting WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
DELETE FROM dc.dc_users_balance WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
DELETE FROM dc.dc_users_symbol_config WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
INSERT INTO dc.dc_users_balance
  (user_id,balance,used_margin,freezed_margin,freezed_commission,update_time,close_by,location)
VALUES
  ('${LOAD_MAKER}',1000000,0,0,0,NOW(),'CORE_STRESS','${LOAD_LOCATION}'),
  ('${LOAD_TAKER}',1000000,0,0,0,NOW(),'CORE_STRESS','${LOAD_LOCATION}');
INSERT INTO dc.dc_users_symbol_config
  (user_id,security_id,symbol,leverage,position_type,update_time,close_by,location,market_indicator)
VALUES
  ('${LOAD_MAKER}','BTCUSDT','BTCUSDT',100,'Cross',NOW(),'CORE_STRESS','${LOAD_LOCATION}','4'),
  ('${LOAD_TAKER}','BTCUSDT','BTCUSDT',100,'Cross',NOW(),'CORE_STRESS','${LOAD_LOCATION}','4');
COMMIT;
SQL
} | mysql_exec dc

log "Reloading the stateful services before the load run."
docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
docker restart dc-saas-gateway >/dev/null
wait_for_route OrderSvr
wait_for_route TDSvr

artifact_dir="${LOAD_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts/stress-${LOAD_RUN_ID}}"
install -d -m 0750 "${artifact_dir}"
before_stats="$(docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' \
  dc-saas-gateway dc-saas-ordersvr dc-saas-tradesvr dc-saas-mdsvr)"
printf '%s\n' "${before_stats}" >"${artifact_dir}/container-stats-before.tsv"

log "Running ${LOAD_ORDERS} resting/cancel and ${LOAD_ORDERS} matched orders at concurrency ${LOAD_CONCURRENCY}."
runner_state="$(docker inspect --format '{{.State.Status}}' "${LOAD_RUNNER_NAME}" 2>/dev/null || true)"
[[ "${runner_state}" == "running" ]] ||
  die "Reusable E2E runner ${LOAD_RUNNER_NAME} is not running; run the Web E2E acceptance first"
runner_work_source="$(docker inspect --format \
  '{{range .Mounts}}{{if eq .Destination "/work"}}{{.Source}}{{end}}{{end}}' \
  "${LOAD_RUNNER_NAME}")"
[[ "${runner_work_source}" == "${SCRIPT_DIR}" ]] ||
  die "Runner /work mount is ${runner_work_source}, expected ${SCRIPT_DIR}"
runner_artifact_source="$(docker inspect --format \
  '{{range .Mounts}}{{if eq .Destination "/artifacts"}}{{.Source}}{{end}}{{end}}' \
  "${LOAD_RUNNER_NAME}")"
[[ -n "${runner_artifact_source}" && "${artifact_dir}" == "${runner_artifact_source}"/* ]] ||
  die "Stress artifact directory is outside runner /artifacts mount"
runner_artifact_rel="${artifact_dir#${runner_artifact_source}/}"

docker exec -w /work \
  -e LOAD_BASE_URL="http://127.0.0.1:${WEB_LISTEN_PORT}" \
  -e LOAD_LOCATION="${LOAD_LOCATION}" -e LOAD_MAKER="${LOAD_MAKER}" -e LOAD_TAKER="${LOAD_TAKER}" \
  -e LOAD_ORDERS="${LOAD_ORDERS}" -e LOAD_CONCURRENCY="${LOAD_CONCURRENCY}" \
  -e LOAD_REQUEST_TIMEOUT_MS="${LOAD_REQUEST_TIMEOUT_MS:-30000}" \
  -e LOAD_SETTLE_MS="${LOAD_SETTLE_MS:-10000}" \
  -e LOAD_RUN_ID="${LOAD_RUN_ID}" \
  -e LOAD_OUTPUT="/artifacts/${runner_artifact_rel}/core-trading-load.json" \
  "${LOAD_RUNNER_NAME}" node core-trading-load.js | tee "${artifact_dir}/core-trading-load.log"

expected_exec=$((LOAD_ORDERS * 2))
expected_orders=$((LOAD_ORDERS * 3))
for _ in $(seq 1 180); do
  persisted="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LOAD_LOCATION}'
  AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}') AND clord_id LIKE 'LOAD-${LOAD_RUN_ID}-%';
SELECT COUNT(*) FROM dc.dc_orders_execorders WHERE location='${LOAD_LOCATION}'
  AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
SQL
  } | mysql_exec dc)"
  mapfile -t progress <<<"${persisted}"
  if [[ "${progress[0]:-0}" == "${expected_orders}" && "${progress[1]:-0}" == "${expected_exec}" ]]; then break; fi
  sleep 2
done

quantity="$(awk -v count="${LOAD_ORDERS}" 'BEGIN {printf "%.8f", count * 0.0001}')"
maker_fee="$(awk -v count="${LOAD_ORDERS}" 'BEGIN {printf "%.8f", count * 0.0012}')"
taker_fee="$(awk -v count="${LOAD_ORDERS}" 'BEGIN {printf "%.8f", count * 0.0036}')"
margin="$(awk -v count="${LOAD_ORDERS}" 'BEGIN {printf "%.8f", count * 0.06}')"

verification="$({
  cat <<SQL
SELECT IF(COUNT(*)=${expected_orders},1,0) FROM dc.dc_orders WHERE location='${LOAD_LOCATION}'
  AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}') AND clord_id LIKE 'LOAD-${LOAD_RUN_ID}-%';
SELECT IF(COUNT(*)=${LOAD_ORDERS},1,0) FROM dc.dc_orders WHERE location='${LOAD_LOCATION}'
  AND clord_id LIKE 'LOAD-${LOAD_RUN_ID}-REST-%' AND ord_status='Cancelled';
SELECT IF(COUNT(*)=$((LOAD_ORDERS * 2)),1,0) FROM dc.dc_orders WHERE location='${LOAD_LOCATION}'
  AND (clord_id LIKE 'LOAD-${LOAD_RUN_ID}-MAKER-%' OR clord_id LIKE 'LOAD-${LOAD_RUN_ID}-TAKER-%')
  AND ord_status='Filled';
SELECT IF(COUNT(*)=${expected_exec},1,0) FROM dc.dc_orders_execorders WHERE location='${LOAD_LOCATION}'
  AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}');
SELECT IF(ABS(p.short_position-${quantity})<0.00000001 AND ABS(p.short_used_margin-${margin})<0.00000001
          AND ABS(b.balance-(1000000-${maker_fee}))<0.00000001 AND ABS(b.used_margin-${margin})<0.00000001
          AND ABS(b.freezed_margin)<0.00000001 AND ABS(b.freezed_commission)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LOAD_LOCATION}' AND p.user_id='${LOAD_MAKER}' AND p.security_id='BTCUSDT';
SELECT IF(ABS(p.long_position-${quantity})<0.00000001 AND ABS(p.long_used_margin-${margin})<0.00000001
          AND ABS(b.balance-(1000000-${taker_fee}))<0.00000001 AND ABS(b.used_margin-${margin})<0.00000001
          AND ABS(b.freezed_margin)<0.00000001 AND ABS(b.freezed_commission)<0.00000001,1,0)
FROM dc.dc_orders_position p JOIN dc.dc_users_balance b ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LOAD_LOCATION}' AND p.user_id='${LOAD_TAKER}' AND p.security_id='BTCUSDT';
SELECT IF(COUNT(*)=COUNT(DISTINCT clord_id),1,0) FROM dc.dc_orders
WHERE location='${LOAD_LOCATION}' AND clord_id LIKE 'LOAD-${LOAD_RUN_ID}-%';
SQL
} | mysql_exec dc)"
mapfile -t checks <<<"${verification}"
[[ "${#checks[@]}" -eq 7 ]] || die "Unexpected load verification output: ${verification}"
for index in "${!checks[@]}"; do
  [[ "${checks[${index}]}" == "1" ]] || die "Load verification check $((index + 1)) failed"
done

log "Restarting stateful services to verify persisted recovery."
docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
docker restart dc-saas-gateway >/dev/null
wait_for_route OrderSvr
wait_for_route TDSvr

recovery="$({
  cat <<SQL
SELECT IF(COUNT(*)=2,1,0) FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LOAD_LOCATION}' AND p.security_id='BTCUSDT'
  AND p.user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}') AND b.used_margin>0;
SELECT IF(COUNT(*)=0,1,0) FROM dc.dc_orders
WHERE location='${LOAD_LOCATION}' AND user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}')
  AND ord_status IN ('New','Partially_Filled');
SQL
} | mysql_exec dc)"
[[ "${recovery}" == $'1\n1' ]] || die "Restart recovery verification failed: ${recovery}"

log "Closing the recovered positions through reduce-only matching."
api_order "{\"OCType\":\"ClOSE\",\"OrderQty\":\"${quantity}\",\"OrdType\":\"Limit\",\"ClOrdID\":\"LOAD-${LOAD_RUN_ID}-CLOSE-SHORT\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"Buy\",\"PositionSide\":\"Short\",\"Price\":\"60000\",\"UserID\":\"${LOAD_MAKER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"true\",\"Location\":\"${LOAD_LOCATION}\"}"
for _ in $(seq 1 60); do
  close_maker_ready="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders WHERE location='${LOAD_LOCATION}'
  AND clord_id='LOAD-${LOAD_RUN_ID}-CLOSE-SHORT' AND ord_status='New';
SQL
  } | mysql_exec dc)"
  [[ "${close_maker_ready}" == "1" ]] && break
  sleep 1
done
[[ "${close_maker_ready:-0}" == "1" ]] || die "Recovered short close order did not rest"
api_order "{\"OCType\":\"ClOSE\",\"OrderQty\":\"${quantity}\",\"OrdType\":\"Limit\",\"ClOrdID\":\"LOAD-${LOAD_RUN_ID}-CLOSE-LONG\",\"Terminal\":\"API\",\"AlgoName\":\"cross\",\"Side\":\"Sell\",\"PositionSide\":\"Long\",\"Price\":\"60000\",\"UserID\":\"${LOAD_TAKER}\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"ReduceOnly\":\"true\",\"Location\":\"${LOAD_LOCATION}\"}"
for _ in $(seq 1 120); do
  close_ok="$({
    cat <<SQL
SELECT IF(COUNT(*)=2,1,0) FROM dc.dc_orders_position p JOIN dc.dc_users_balance b
  ON b.location=p.location AND b.user_id=p.user_id
WHERE p.location='${LOAD_LOCATION}' AND p.security_id='BTCUSDT'
  AND p.user_id IN ('${LOAD_MAKER}','${LOAD_TAKER}')
  AND ABS(p.long_position)<0.00000001 AND ABS(p.short_position)<0.00000001
  AND ABS(p.long_used_margin)<0.00000001 AND ABS(p.short_used_margin)<0.00000001
  AND ABS(b.used_margin)<0.00000001 AND ABS(b.freezed_margin)<0.00000001
  AND ABS(b.freezed_commission)<0.00000001;
SQL
  } | mysql_exec dc)"
  [[ "${close_ok}" == "1" ]] && break
  sleep 1
done
[[ "${close_ok:-0}" == "1" ]] || die "Recovered positions did not close cleanly"

docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' \
  dc-saas-gateway dc-saas-ordersvr dc-saas-tradesvr dc-saas-mdsvr \
  >"${artifact_dir}/container-stats-after.tsv"
docker inspect --format '{{.Name}}\t{{.RestartCount}}\t{{.State.OOMKilled}}\t{{.State.Status}}' \
  dc-saas-gateway dc-saas-ordersvr dc-saas-tradesvr dc-saas-mdsvr \
  >"${artifact_dir}/container-health-after.tsv"
if grep -Eq $'\ttrue\t|\texited$|\tdead$' "${artifact_dir}/container-health-after.tsv"; then
  die "A core container was OOM-killed or stopped during load"
fi

log "PASS: load, matching accounting, uniqueness and restart recovery checks succeeded. Artifacts: ${artifact_dir}"
