#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
SKIP_HOST_PREPARE="false"
SKIP_PULL="false"

log() {
  printf '[saas-deploy] %s\n' "$*"
}

die() {
  printf '[saas-deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: sudo ./deploy-saas.sh [--skip-host-prepare] [--skip-pull]

Deploy the standalone DC cryptocurrency SaaS stack. This script never starts,
stops, or reconfigures the independent quantitative-trading stack.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --skip-host-prepare)
      SKIP_HOST_PREPARE="true"
      ;;
    --skip-pull)
      SKIP_PULL="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ "${EUID}" -eq 0 ]] || die "Run as root or with sudo."
cd "${SCRIPT_DIR}"

generate_secret() {
  command -v openssl >/dev/null 2>&1 || die "openssl is required to generate runtime secrets."
  openssl rand -hex 24
}

set_env_value() {
  local key="$1"
  local value="$2"
  sed -i "s|^${key}=.*$|${key}=${value}|" "${ENV_FILE}"
}

migrate_env_value() {
  local key="$1"
  local old_value="$2"
  local new_value="$3"
  if grep -Fqx "${key}=${old_value}" "${ENV_FILE}"; then
    set_env_value "${key}" "${new_value}"
  fi
}

ensure_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return 0
  fi

  cp .env.example "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
  set_env_value MYSQL_PASSWORD "$(generate_secret)"
  set_env_value MYSQL_ROOT_PASSWORD "$(generate_secret)"
  set_env_value CLICKHOUSE_PASSWORD "$(generate_secret)"
  set_env_value LOGIN_DEFAULT_PASSWORD "$(generate_secret)"
  log "Created ${ENV_FILE} with generated local secrets."
}

ensure_env_defaults() {
  if ! grep -q '^IMAGE_SOURCE=' "${ENV_FILE}"; then
    printf '\nIMAGE_SOURCE=registry\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^BUILD_ROOT=' "${ENV_FILE}"; then
    printf 'BUILD_ROOT=/opt/dc-saas-build\n' >> "${ENV_FILE}"
  fi
  migrate_env_value IMAGE_SOURCE local registry
  migrate_env_value GW_IMAGE_REPOSITORY dc-saas/gw ghcr.io/bliplink/gw
  migrate_env_value LOGINSVR_IMAGE_REPOSITORY dc-saas/loginsvr ghcr.io/bliplink/loginsvr
  migrate_env_value MDSVR_IMAGE_REPOSITORY dc-saas/mdsvr ghcr.io/bliplink/mdsvr
  migrate_env_value APSSVR_IMAGE_REPOSITORY dc-saas/apssvr ghcr.io/bliplink/apssvr
  migrate_env_value ORDERSVR_IMAGE_REPOSITORY dc-saas/ordersvr ghcr.io/bliplink/ordersvr
  migrate_env_value TRADESVR_IMAGE_REPOSITORY dc-saas/tradesvr ghcr.io/bliplink/tradesvr
  migrate_env_value LIQSVR_IMAGE_REPOSITORY dc-saas/liqsvr ghcr.io/bliplink/liqsvr
  migrate_env_value MANAGERSVR_IMAGE_REPOSITORY dc-saas/managersvr ghcr.io/bliplink/managersvr
  migrate_env_value ADMINSVR_IMAGE_REPOSITORY dc-saas/adminsvr ghcr.io/bliplink/adminsvr
  migrate_env_value TRADE_WEB_IMAGE_REPOSITORY dc-saas/dc-trade-web ghcr.io/skt-walter/dc-trade-web
  migrate_env_value REQUIRE_GHCR_LOGIN true false
  if grep -q '^ZOOKEEPER_TAG=v0.0.3-test$' "${ENV_FILE}"; then
    sed -i 's/^ZOOKEEPER_TAG=v0.0.3-test$/ZOOKEEPER_TAG=3.8.4/' "${ENV_FILE}"
  fi
}

ensure_host_runtime() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return 0
  fi
  [[ "${SKIP_HOST_PREPARE}" == "false" ]] ||
    die "Docker/Compose is missing and --skip-host-prepare was supplied."
  "${SCRIPT_DIR}/prepare-host.sh"
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
}

validate_runtime_root() {
  [[ "${DEPLOY_ROOT}" == /* ]] || die "DEPLOY_ROOT must be absolute."
  [[ "${DEPLOY_ROOT}" != "/" ]] || die "DEPLOY_ROOT cannot be /."
  [[ "${DEPLOY_ROOT}" != "/opt" ]] || die "DEPLOY_ROOT cannot be /opt."
}

port_is_listening() {
  local port="$1"
  ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${port}$"
}

validate_initial_ports() {
  local existing port
  existing="$(docker ps -a --format '{{.Names}}' | grep '^dc-saas-' || true)"
  [[ -z "${existing}" ]] || return 0

  for port in "${MYSQL_PORT}" "${CLICKHOUSE_HTTP_PORT}" "${CLICKHOUSE_NATIVE_PORT}" "${ZOOKEEPER_PORT}" "${ZOOKEEPER_JMX_PORT}" "${GW_TCP_PORT}" "${GW_WEBSOCKET_PORT}" "${GW_HTTP_PORT}" "${LOGINSVR_HTTP_PORT}" "${LOGINSVR_GW_PORT}" "${MDSVR_GW_PORT}" "${APSSVR_GW_PORT}" "${ORDERSVR_GW_PORT}" "${TRADESVR_GW_PORT}" "${LIQSVR_GW_PORT}" "${MANAGERSVR_GW_PORT}" "${ADMINSVR_GW_PORT}" "${WEB_LISTEN_PORT}"; do
    if port_is_listening "${port}"; then
      die "Port ${port} is already in use. Existing non-SaaS services were not changed."
    fi
  done
}

prepare_runtime_directories() {
  install -d -m 0750 "${DEPLOY_ROOT}" "${DEPLOY_ROOT}/control" "${DEPLOY_ROOT}/data" "${DEPLOY_ROOT}/data/mysql" "${DEPLOY_ROOT}/data/clickhouse" "${DEPLOY_ROOT}/data/zookeeper" "${DEPLOY_ROOT}/log" "${DEPLOY_ROOT}/log/clickhouse" "${DEPLOY_ROOT}/log/zookeeper"
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" "$@"
}

wait_for_health() {
  local container="$1"
  local timeout_seconds="${2:-300}"
  local start status
  start="$(date +%s)"

  while true; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container}" 2>/dev/null || true)"
    case "${status}" in
      healthy|running)
        log "${container}: ${status}"
        return 0
        ;;
      unhealthy|exited|dead)
        docker logs --tail 100 "${container}" >&2 || true
        die "${container} entered state ${status}"
        ;;
    esac

    if (( $(date +%s) - start >= timeout_seconds )); then
      docker logs --tail 100 "${container}" >&2 || true
      die "Timed out waiting for ${container}; last state: ${status:-missing}"
    fi
    sleep 5
  done
}

verify_ghcr_access() {
  [[ "${REQUIRE_GHCR_LOGIN:-false}" == "true" ]] || return 0
  if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
    printf '%s' "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
    return 0
  fi

  if docker manifest inspect "${TRADESVR_IMAGE_REPOSITORY}:${TRADESVR_TAG}" >/dev/null 2>&1; then
    log "Existing Docker credentials can read the private GHCR SaaS packages."
    return 0
  fi

  die "Private GHCR images are not readable. Run 'docker login ghcr.io' with a classic PAT containing read:packages, or set GHCR_USERNAME/GHCR_TOKEN in the protected runtime environment."
}

ensure_env_file
ensure_env_defaults
ensure_host_runtime
load_env
validate_runtime_root
validate_initial_ports
prepare_runtime_directories
"${SCRIPT_DIR}/generate-saas-configs.sh" "${ENV_FILE}"
verify_ghcr_access

compose config --quiet

if [[ "${IMAGE_SOURCE:-local}" == "local" ]]; then
  if [[ "${SKIP_PULL}" == "false" ]]; then
    log "Building SaaS application images from the dedicated source branches."
    "${SCRIPT_DIR}/build-saas-images.sh" "${ENV_FILE}"
  fi
  log "Pulling public infrastructure images."
  compose pull mysql clickhouse zookeeper
elif [[ "${IMAGE_SOURCE}" == "registry" ]]; then
  if [[ "${SKIP_PULL}" == "false" ]]; then
    log "Pulling SaaS application and infrastructure images."
    compose pull
  fi
else
  die "IMAGE_SOURCE must be local or registry."
fi

log "Starting isolated MySQL, ClickHouse, and ZooKeeper."
compose up -d mysql clickhouse zookeeper
wait_for_health dc-saas-mysql 420
wait_for_health dc-saas-clickhouse 420
wait_for_health dc-saas-zookeeper 120

log "Starting the SaaS application services and dc-trade-web."
compose up -d
wait_for_health dc-saas-trade-web 300

"${SCRIPT_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"
log "DC SaaS is ready at http://$(hostname -I | awk '{print $1}'):${WEB_LISTEN_PORT}/"
