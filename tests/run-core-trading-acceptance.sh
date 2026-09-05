#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
CORE_LOCATION="${CORE_E2E_LOCATION:-CORE_E2E}"
CORE_BUYER="${CORE_E2E_BUYER:-corebuyer}"
CORE_SELLER="${CORE_E2E_SELLER:-coreseller}"

log() {
  printf '[core-acceptance] %s\n' "$*"
}

die() {
  printf '[core-acceptance] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"
[[ "${CORE_LOCATION}" == *_E2E ]] ||
  die "CORE_E2E_LOCATION must be an isolated *_E2E location"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

wait_for_port() {
  local port="$1" service="$2" start
  start="$(date +%s)"
  until ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${port}$"; do
    if (( $(date +%s) - start >= 120 )); then
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
      --data-binary "@${request_file}" "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
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

log "Waiting for all core service ports before validating the deployed SaaS stack."
while read -r port service; do
  wait_for_port "${port}" "${service}"
done <<PORTS
${GW_TCP_PORT} gateway
${LOGINSVR_GW_PORT} loginsvr
${MDSVR_GW_PORT} mdsvr
${APSSVR_GW_PORT} apssvr
${ORDERSVR_GW_PORT} ordersvr
${TRADESVR_GW_PORT} tradesvr
${LIQSVR_GW_PORT} liqsvr
${MANAGERSVR_GW_PORT} managersvr
${ADMINSVR_GW_PORT} adminsvr
PORTS

log "Validating the deployed SaaS stack."
"${DEPLOY_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"

log "Running MySQL and ClickHouse location-isolation smoke tests."
ENV_FILE="${ENV_FILE}" "${DEPLOY_DIR}/smoke-test-location.sh"

log "Running strict order-rule validation in an isolated acceptance location."
ENV_FILE="${ENV_FILE}" \
RULE_E2E_LOCATION="${CORE_LOCATION}" \
RULE_E2E_MAKER_ONE="${CORE_BUYER}_rulemaker1" \
RULE_E2E_MAKER_TWO="${CORE_BUYER}_rulemaker2" \
RULE_E2E_TAKER="${CORE_BUYER}_ruletaker" \
RULE_E2E_SELF_USER="${CORE_BUYER}_ruleself" \
  "${SCRIPT_DIR}/run-trading-rules-e2e-host.sh"

log "Running browser login, deposit, order, cancel, match, market close, history and recent-trade flow in ${CORE_LOCATION}."
ENV_FILE="${ENV_FILE}" \
E2E_LOCATION="${CORE_LOCATION}" \
E2E_BUYER="${CORE_BUYER}" \
E2E_SELLER="${CORE_SELLER}" \
E2E_PASSWORD="${E2E_PASSWORD}" \
  "${SCRIPT_DIR}/run-web-trading-e2e-host.sh"

log "Validating the draggable, resizable, persistent and bilingual professional Web workspace."
ENV_FILE="${ENV_FILE}" \
E2E_LOCATION="${CORE_LOCATION}" \
E2E_USER="${CORE_BUYER}" \
E2E_PASSWORD="${E2E_PASSWORD}" \
  "${SCRIPT_DIR}/run-web-workspace-e2e-host.sh"

log "Validating the 390px touch-friendly, overflow-free and bilingual mobile trading workspace."
ENV_FILE="${ENV_FILE}" \
E2E_LOCATION="${CORE_LOCATION}" \
E2E_USER="${CORE_BUYER}" \
E2E_PASSWORD="${E2E_PASSWORD}" \
  "${SCRIPT_DIR}/run-web-mobile-e2e-host.sh"

log "Running LiqSvr partial-liquidation flow in the same ${CORE_LOCATION} location."
ENV_FILE="${ENV_FILE}" \
LIQ_E2E_LOCATION="${CORE_LOCATION}" \
LIQ_E2E_OTHER_LOCATION="${CORE_LOCATION}_FOREIGN" \
LIQ_E2E_USER="${CORE_BUYER}_liq" \
LIQ_E2E_MAKER="${CORE_BUYER}_liqmaker" \
LIQ_E2E_FOREIGN_USER="${CORE_BUYER}_liqforeign" \
  "${SCRIPT_DIR}/run-liquidation-e2e-host.sh"

log "Running natural final-liquidation, insurance and step-aligned ADL flow in ${CORE_LOCATION}."
ENV_FILE="${ENV_FILE}" \
FINAL_LIQ_E2E_LOCATION="${CORE_LOCATION}" \
FINAL_LIQ_E2E_OTHER_LOCATION="${CORE_LOCATION}_FOREIGN" \
FINAL_LIQ_E2E_USER="${CORE_BUYER}_final" \
FINAL_LIQ_E2E_MAKER="${CORE_BUYER}_finalmaker" \
FINAL_LIQ_E2E_ADL_USER="${CORE_BUYER}_finaladl" \
FINAL_LIQ_E2E_FOREIGN_USER="${CORE_BUYER}_finalforeign" \
  "${SCRIPT_DIR}/run-final-liquidation-e2e-host.sh"

log "Running deterministic multi-candidate ADL ranking flow in the same ${CORE_LOCATION} location."
ENV_FILE="${ENV_FILE}" \
ADL_E2E_LOCATION="${CORE_LOCATION}" \
ADL_E2E_OTHER_LOCATION="${CORE_LOCATION}_FOREIGN" \
ADL_E2E_REFERENCE_PRICE=60000 \
  "${SCRIPT_DIR}/run-adl-e2e-host.sh"

log "Refreshing GW routes after the ADL fixture restarted TradeSvr."
docker restart dc-saas-gateway >/dev/null
wait_for_gateway_route OrderSvr
wait_for_gateway_route TDSvr

log "Revalidating health after TradeSvr restart and ADL settlement."
"${DEPLOY_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"

if [[ "${RUN_CORE_STRESS:-false}" == "true" ]]; then
  log "Running the opt-in full-stack concurrent load and restart-recovery gate."
  ENV_FILE="${ENV_FILE}" \
  LOAD_LOCATION="${CORE_LOCATION}" \
  LOAD_MAKER="${CORE_BUYER}_stressmaker" \
  LOAD_TAKER="${CORE_BUYER}_stresstaker" \
    "${SCRIPT_DIR}/run-core-trading-stress-host.sh"
fi

log "Capturing effective JVM heaps and container memory limits."
memory_limit_bytes() {
  local value="$1"
  if [[ "${value}" =~ ^([0-9]+)[mM]$ ]]; then
    echo $((10#${BASH_REMATCH[1]} * 1024 * 1024))
  elif [[ "${value}" =~ ^([0-9]+)[gG]$ ]]; then
    echo $((10#${BASH_REMATCH[1]} * 1024 * 1024 * 1024))
  elif [[ "${value}" =~ ^[0-9]+$ ]]; then
    echo "${value}"
  else
    die "Unsupported memory-limit format: ${value}"
  fi
}

while read -r container expected_xmx configured_memory; do
  expected_memory="$(memory_limit_bytes "${configured_memory}")"
  java_command="$(docker exec "${container}" sh -c "ps -ef | grep '[j]ava' | head -n 1")"
  memory_bytes="$(docker inspect --format '{{.HostConfig.Memory}}' "${container}")"
  [[ -n "${java_command}" && "${memory_bytes}" =~ ^[1-9][0-9]+$ ]] ||
    die "Missing JVM or memory limit for ${container}"
  grep -Fq -- "-Xmx${expected_xmx}" <<<"${java_command}" ||
    die "Effective JVM heap for ${container} is not -Xmx${expected_xmx}: ${java_command}"
  (( memory_bytes == expected_memory )) ||
    die "Memory limit for ${container} is ${memory_bytes}, expected ${expected_memory}"
  printf '[core-acceptance] MEMORY %s limit_bytes=%s effective_xmx=%s\n' \
    "${container}" "${memory_bytes}" "${expected_xmx}"
done <<MEMORY_EXPECTATIONS
dc-saas-gateway 256m ${GW_MEMORY_LIMIT:-512m}
dc-saas-loginsvr 256m ${LOGINSVR_MEMORY_LIMIT:-384m}
dc-saas-mdsvr 448m ${MDSVR_MEMORY_LIMIT:-640m}
dc-saas-apssvr 448m ${APSSVR_MEMORY_LIMIT:-640m}
dc-saas-ordersvr 448m ${ORDERSVR_MEMORY_LIMIT:-640m}
dc-saas-tradesvr 384m ${TRADESVR_MEMORY_LIMIT:-896m}
dc-saas-liqsvr 256m ${LIQSVR_MEMORY_LIMIT:-384m}
dc-saas-managersvr 256m ${MANAGERSVR_MEMORY_LIMIT:-384m}
dc-saas-adminsvr 256m ${ADMINSVR_MEMORY_LIMIT:-384m}
dc-saas-robotsvr 256m ${ROBOTSVR_MEMORY_LIMIT:-384m}
MEMORY_EXPECTATIONS

log "PASS: the complete single-location core trading acceptance flow succeeded."
