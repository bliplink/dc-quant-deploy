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

log "Validating the deployed SaaS stack."
"${DEPLOY_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"

log "Running MySQL and ClickHouse location-isolation smoke tests."
ENV_FILE="${ENV_FILE}" "${DEPLOY_DIR}/smoke-test-location.sh"

log "Running browser login, deposit, order, cancel, match, market close, history and recent-trade flow in ${CORE_LOCATION}."
ENV_FILE="${ENV_FILE}" \
E2E_LOCATION="${CORE_LOCATION}" \
E2E_BUYER="${CORE_BUYER}" \
E2E_SELLER="${CORE_SELLER}" \
E2E_PASSWORD="${E2E_PASSWORD}" \
  "${SCRIPT_DIR}/run-web-trading-e2e-host.sh"

log "Running insurance-deficit and transactional ADL flow in the same ${CORE_LOCATION} location."
ENV_FILE="${ENV_FILE}" \
ADL_E2E_LOCATION="${CORE_LOCATION}" \
ADL_E2E_OTHER_LOCATION="${CORE_LOCATION}_FOREIGN" \
ADL_E2E_REFERENCE_PRICE=60000 \
  "${SCRIPT_DIR}/run-adl-e2e-host.sh"

log "Revalidating health after TradeSvr restart and ADL settlement."
"${DEPLOY_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"

log "Capturing effective JVM heaps and container memory limits."
while read -r container expected_xmx expected_memory; do
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
done <<'MEMORY_EXPECTATIONS'
dc-saas-gateway 512m 805306368
dc-saas-loginsvr 512m 805306368
dc-saas-mdsvr 768m 1073741824
dc-saas-apssvr 768m 1073741824
dc-saas-ordersvr 768m 1073741824
dc-saas-tradesvr 640m 939524096
dc-saas-liqsvr 512m 805306368
dc-saas-managersvr 512m 805306368
dc-saas-adminsvr 512m 805306368
MEMORY_EXPECTATIONS

log "PASS: the complete single-location core trading acceptance flow succeeded."
