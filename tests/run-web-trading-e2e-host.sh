#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_BASE_URL="${E2E_BASE_URL:-}"
E2E_LOCATION="${E2E_LOCATION:-WEB_E2E}"
E2E_BUYER="${E2E_BUYER:-webbuyer}"
E2E_SELLER="${E2E_SELLER:-webseller}"
E2E_PREPARE_BASELINE="${E2E_PREPARE_BASELINE:-true}"
E2E_RESTART_SERVICES="${E2E_RESTART_SERVICES:-true}"
E2E_RUNNER_NAME="${E2E_RUNNER_NAME:-dc-saas-web-e2e-runner}"
E2E_RUNNER_IMAGE="${E2E_RUNNER_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"

log() {
  printf '[web-e2e-host] %s\n' "$*"
}

die() {
  printf '[web-e2e-host] ERROR: %s\n' "$*" >&2
  exit 1
}

is_true() {
  [[ "$1" == "true" || "$1" == "1" || "$1" == "yes" ]]
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"

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

wait_for_gateway_route() {
  local server_name="$1" start request_file response
  start="$(date +%s)"
  request_file="$(mktemp)"
  chmod 0600 "${request_file}"
  printf '{"serverName":"%s","method":"__e2e_readiness__","content":{}}\n' \
    "${server_name}" >"${request_file}"
  while true; do
    response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
      --data-binary "@${request_file}" "${E2E_BASE_URL}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" ]] && ! grep -Fq 'is not Online' <<<"${response}"; then
      rm -f "${request_file}"
      return 0
    fi
    if (( $(date +%s) - start >= 120 )); then
      rm -f "${request_file}"
      die "${server_name} did not become routable through GW"
    fi
    sleep 2
  done
}

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}}"
artifact_dir="${E2E_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts}"
install -d -m 0750 "${artifact_dir}"

if is_true "${E2E_PREPARE_BASELINE}"; then
  ENV_FILE="${ENV_FILE}" \
  E2E_LOCATION="${E2E_LOCATION}" \
  E2E_BUYER="${E2E_BUYER}" \
  E2E_SELLER="${E2E_SELLER}" \
  E2E_PASSWORD="${E2E_PASSWORD}" \
    "${SCRIPT_DIR}/prepare-web-trading-e2e.sh"
elif is_true "${E2E_RESTART_SERVICES}"; then
  die "E2E_RESTART_SERVICES=true requires E2E_PREPARE_BASELINE=true"
else
  log "Using the existing E2E database baseline without mutation."
fi

if is_true "${E2E_RESTART_SERVICES}"; then
  log "Restarting OrderSvr and TradeSvr on the clean E2E database baseline."
  docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
else
  log "Keeping running trading services; only readiness will be checked."
fi
wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
if is_true "${E2E_RESTART_SERVICES}"; then
  log "Restarting GW so it resolves the refreshed OrderSvr and TDSvr routes."
  docker restart dc-saas-gateway >/dev/null
fi
wait_for_gateway_route OrderSvr
wait_for_gateway_route TDSvr

login_api_check() {
  local user="$1"
  local request_file response
  request_file="$(mktemp)"
  chmod 0600 "${request_file}"
  cat >"${request_file}" <<JSON
{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"${user}","user_name":"${user}","password":"${E2E_PASSWORD}","method":"login","client_type":"WEB","cid":"E2E_PRECHECK_${user}","Location":"${E2E_LOCATION}"}}
JSON
  response="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' --data-binary "@${request_file}" "${E2E_BASE_URL}/httpapi/")" || {
    rm -f "${request_file}"
    die "Login API request failed for ${user}"
  }
  rm -f "${request_file}"
  grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}" || die "Login API rejected ${user}"
  grep -Fq "\"user_id\":\"${user}\"" <<<"${response}" || die "Login API returned another user for ${user}"
}

login_api_check "${E2E_BUYER}"
login_api_check "${E2E_SELLER}"

wrong_location_request="$(mktemp)"
chmod 0600 "${wrong_location_request}"
cat >"${wrong_location_request}" <<JSON
{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"${E2E_BUYER}","user_name":"${E2E_BUYER}","password":"${E2E_PASSWORD}","method":"login","client_type":"WEB","cid":"E2E_WRONG_LOCATION","Location":"${E2E_LOCATION}_WRONG"}}
JSON
wrong_location_response="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' --data-binary "@${wrong_location_request}" "${E2E_BASE_URL}/httpapi/")" || {
  rm -f "${wrong_location_request}"
  die "Wrong-location login precheck could not reach LoginSvr"
}
rm -f "${wrong_location_request}"
if grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${wrong_location_response}"; then
  die "LoginSvr accepted valid credentials under the wrong location"
fi
log "Login API precheck passed and wrong-location authentication was rejected."

runner_state="$(docker inspect --format '{{.State.Status}}' "${E2E_RUNNER_NAME}" 2>/dev/null || true)"
if [[ -n "${runner_state}" ]]; then
  runner_work_source="$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/work"}}{{.Source}}{{end}}{{end}}' \
    "${E2E_RUNNER_NAME}")"
  if [[ "${runner_work_source}" != "${SCRIPT_DIR}" ]]; then
    log "Replacing stale Playwright runner mounted from ${runner_work_source}."
    docker rm -f "${E2E_RUNNER_NAME}" >/dev/null
    runner_state=""
  fi
fi
if [[ -z "${runner_state}" ]]; then
  log "Creating reusable Playwright runner ${E2E_RUNNER_NAME}."
  docker run -d \
    --name "${E2E_RUNNER_NAME}" \
    --network host \
    --label dc.saas.role=web-e2e-runner \
    -v "${SCRIPT_DIR}:/work:ro" \
    -v "${artifact_dir}:/artifacts" \
    -v dc-saas-web-e2e-npm-cache:/root/.npm \
    -v dc-saas-web-e2e-runner:/runner \
    "${E2E_RUNNER_IMAGE}" sleep infinity >/dev/null
else
  runner_role="$(docker inspect --format '{{index .Config.Labels "dc.saas.role"}}' "${E2E_RUNNER_NAME}")"
  [[ "${runner_role}" == "web-e2e-runner" ]] ||
    die "Container ${E2E_RUNNER_NAME} exists but is not a SaaS web E2E runner"
  if [[ "${runner_state}" != "running" ]]; then
    docker start "${E2E_RUNNER_NAME}" >/dev/null
  fi
fi

docker exec \
  -e E2E_BASE_URL="${E2E_BASE_URL}" \
  -e E2E_LOCATION="${E2E_LOCATION}" \
  -e E2E_BUYER="${E2E_BUYER}" \
  -e E2E_SELLER="${E2E_SELLER}" \
  -e E2E_PASSWORD="${E2E_PASSWORD}" \
  -e E2E_ARTIFACT_DIR=/artifacts \
  "${E2E_RUNNER_NAME}" bash /work/run-web-trading-e2e.sh

log "Verifying authoritative order, execution and position state in MySQL."
db_ready="false"
for attempt in $(seq 1 30); do
  db_result="$({
    cat <<SQL
SELECT COUNT(*) FROM dc.dc_orders_position
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND (long_position <> 0 OR short_position <> 0
       OR long_locked_position <> 0 OR short_locked_position <> 0
       OR long_used_margin <> 0 OR short_used_margin <> 0);
SELECT COUNT(*) FROM dc.dc_orders
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND ord_status IN ('Newing','New','PartiallyFilled','Partially_Filled','PendingCancel','Pending_Cancel');
SELECT COUNT(*) FROM dc.dc_users_balance
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND (used_margin <> 0 OR freezed_margin <> 0 OR freezed_commission <> 0);
SELECT COUNT(*) FROM dc.dc_orders_execorders
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND UPPER(oc_type)='OPEN' AND last_qty > 0;
SELECT COUNT(*) FROM dc.dc_orders_execorders
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}')
  AND UPPER(oc_type)='CLOSE' AND last_qty > 0;
SELECT COUNT(*) FROM dc.dc_orders
WHERE location='${E2E_LOCATION}' AND user_id='${E2E_BUYER}'
  AND UPPER(oc_type)='CLOSE' AND reduce_only=1
  AND ord_type='Market' AND timeinforce='IOC' AND ord_status='Filled';
SELECT COUNT(*) FROM dc.dc_users_posting
WHERE location='${E2E_LOCATION}'
  AND user_id IN ('${E2E_BUYER}','${E2E_SELLER}') AND type=1 AND amount='100000';
SQL
  } | mysql_exec dc)"
  mapfile -t db_rows <<<"${db_result}"
  if [[ "${#db_rows[@]}" -eq 7 ]] \
    && [[ "${db_rows[0]}" == "0" ]] \
    && [[ "${db_rows[1]}" == "0" ]] \
    && [[ "${db_rows[2]}" == "0" ]] \
    && (( db_rows[3] >= 2 )) \
    && (( db_rows[4] >= 1 )) \
    && (( db_rows[5] >= 1 )) \
    && (( db_rows[6] >= 2 )); then
    db_ready="true"
    break
  fi
  if [[ "${attempt}" -eq 1 ]]; then
    log "Waiting for asynchronous TradeSvr persistence to converge."
  fi
  sleep 1
done

[[ "${db_ready}" == "true" ]] || log "Database state did not converge within 30 seconds."
[[ "${#db_rows[@]}" -eq 7 ]] || die "Unexpected database verification output: ${db_result}"
[[ "${db_rows[0]}" == "0" ]] || die "E2E accounts still have non-flat or locked positions: ${db_rows[0]}"
[[ "${db_rows[1]}" == "0" ]] || die "E2E accounts still have live orders: ${db_rows[1]}"
[[ "${db_rows[2]}" == "0" ]] || die "E2E accounts retain frozen or used margin after cancel/close: ${db_rows[2]}"
(( db_rows[3] >= 2 )) || die "Missing authoritative open executions: ${db_rows[3]}"
(( db_rows[4] >= 1 )) || die "Missing authoritative close execution: ${db_rows[4]}"
(( db_rows[5] >= 1 )) || die "Missing filled reduce-only Market/IOC close order: ${db_rows[5]}"
(( db_rows[6] >= 2 )) || die "Missing authoritative deposits: ${db_rows[6]}"

log "Browser trading acceptance passed; artifacts: ${artifact_dir}."
