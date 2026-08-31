#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
LOCK_FILE="${SAAS_AUTO_UPDATE_LOCK_FILE:-/tmp/dc-saas-auto-update.lock}"
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

if [[ "${SAAS_DEPLOY_LOCK_HELD:-false}" != "true" ]]; then
  command -v flock >/dev/null 2>&1 || die "flock is required."
  exec 8>"${LOCK_FILE}"
  flock -n 8 || die "Another SaaS deploy, uninstall, or auto-update run holds ${LOCK_FILE}."
fi

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
  set_env_value PLATFORM_ADMIN_PASSWORD "$(generate_secret)"
  log "Created ${ENV_FILE} with generated local secrets."
}

ensure_env_defaults() {
  if ! grep -q '^IMAGE_SOURCE=' "${ENV_FILE}"; then
    printf '\nIMAGE_SOURCE=registry\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^BUILD_ROOT=' "${ENV_FILE}"; then
    printf 'BUILD_ROOT=/data/dc-saas-build\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^PLATFORM_ADMIN_USERNAME=' "${ENV_FILE}"; then
    printf 'PLATFORM_ADMIN_USERNAME=platformadmin\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^PLATFORM_ADMIN_PASSWORD=' "${ENV_FILE}"; then
    printf 'PLATFORM_ADMIN_PASSWORD=%s\n' "$(generate_secret)" >> "${ENV_FILE}"
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
  migrate_env_value ROBOTSVR_IMAGE_REPOSITORY dc-saas/robotsvr ghcr.io/bliplink/robotsvr
  migrate_env_value TRADE_WEB_IMAGE_REPOSITORY dc-saas/dc-trade-web ghcr.io/bliplink/dc-saas-trade-web
  migrate_env_value TRADE_WEB_IMAGE_REPOSITORY ghcr.io/skt-walter/dc-trade-web ghcr.io/bliplink/dc-saas-trade-web
  # Public application images use moving saas-crypto tags so the digest-based
  # updater can detect and deploy a new Web build like every other SaaS service.
  for legacy_web_tag in \
    source-2ed6e68f3ad45a65cb184b5397abc9f752719721 \
    source-97b3afe88928fe0c6b26a8564d88ae5168556dba \
    source-cbd7e5a12c7a083b30383922263101f1a730cb3a \
    source-d383dbff18116090b5dec29fa07757bccc5abb53 \
    source-000dd5fde5731e7bd70492b09333985574f1ea0e \
    source-6d20d6b9e6361017d7892f8018c7d68a0130e284 \
    source-dbf69d5e0090f981eac546681a4a596275a5b22c \
    source-04ded17cd3de3a5fb8a5cfd0b25d2cce72ca7676; do
    migrate_env_value TRADE_WEB_TAG "${legacy_web_tag}" saas-crypto
  done
  migrate_env_value REQUIRE_GHCR_LOGIN true false
  if ! grep -q '^SAAS_MIN_TOTAL_MEMORY_MB=' "${ENV_FILE}"; then
    printf 'SAAS_MIN_TOTAL_MEMORY_MB=7680\n' >> "${ENV_FILE}"
  fi
  migrate_env_value SAAS_MIN_AVAILABLE_MEMORY_MB 8192 2048
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
  local resolved_root resolved_build_root
  [[ "${DEPLOY_ROOT}" == /* ]] || die "DEPLOY_ROOT must be absolute."
  resolved_root="$(readlink -m "${DEPLOY_ROOT}")"
  case "${resolved_root}" in
    /data/dc-saas-runtime|/opt/dc-saas-runtime) ;;
    *) die "DEPLOY_ROOT must resolve to /data/dc-saas-runtime or /opt/dc-saas-runtime." ;;
  esac
  [[ ! -L "${DEPLOY_ROOT}" ]] || die "DEPLOY_ROOT cannot be a symbolic link."
  resolved_build_root="$(readlink -m "${BUILD_ROOT:-/data/dc-saas-build}")"
  case "${resolved_build_root}" in
    /data/dc-saas-build|/opt/dc-saas-build) ;;
    *) die "BUILD_ROOT must resolve to /data/dc-saas-build or /opt/dc-saas-build." ;;
  esac
}

available_memory_mb() {
  awk '/^MemAvailable:/ {printf "%d\n", $2 / 1024}' /proc/meminfo
}

total_memory_mb() {
  awk '/^MemTotal:/ {printf "%d\n", $2 / 1024}' /proc/meminfo
}

available_disk_gb() {
  local target="$1"
  while [[ ! -e "${target}" && "${target}" != "/" ]]; do target="$(dirname "${target}")"; done
  df -Pk "${target}" | awk 'NR==2 {printf "%d\n", $4 / 1024 / 1024}'
}

validate_runtime_capacity() {
  local memory_mb total_mb runtime_disk_gb docker_root docker_disk_gb
  memory_mb="$(available_memory_mb)"
  total_mb="$(total_memory_mb)"
  runtime_disk_gb="$(available_disk_gb "${DEPLOY_ROOT}")"
  docker_root="$(docker info --format '{{.DockerRootDir}}')"
  docker_disk_gb="$(available_disk_gb "${docker_root}")"
  (( total_mb >= ${SAAS_MIN_TOTAL_MEMORY_MB:-7680} )) ||
    die "Only ${total_mb} MiB total memory is installed; at least ${SAAS_MIN_TOTAL_MEMORY_MB:-7680} MiB is required."
  (( memory_mb >= ${SAAS_MIN_AVAILABLE_MEMORY_MB:-2048} )) ||
    die "Only ${memory_mb} MiB memory is available; at least ${SAAS_MIN_AVAILABLE_MEMORY_MB:-2048} MiB is required."
  (( runtime_disk_gb >= ${SAAS_MIN_RUNTIME_DISK_GB:-100} )) ||
    die "Only ${runtime_disk_gb} GiB is free for ${DEPLOY_ROOT}; at least ${SAAS_MIN_RUNTIME_DISK_GB:-100} GiB is required."
  (( docker_disk_gb >= ${SAAS_MIN_DOCKER_DISK_GB:-15} )) ||
    die "Only ${docker_disk_gb} GiB is free below Docker root ${docker_root}; at least ${SAAS_MIN_DOCKER_DISK_GB:-15} GiB is required."
  log "Capacity preflight passed: ${total_mb} MiB total/${memory_mb} MiB available memory, ${runtime_disk_gb} GiB runtime disk, ${docker_disk_gb} GiB Docker disk available."
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

compose_pull() {
  # Small production hosts and restricted egress links can stall when Compose
  # opens one registry connection per service. Pull serially by default.
  COMPOSE_PARALLEL_LIMIT="${COMPOSE_PULL_PARALLEL_LIMIT:-1}" \
    docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" pull "$@"
}

compose_up() {
  # The production host uses Docker's vfs driver on XFS. Serial container
  # creation avoids long XFS log stalls while copying multiple Java rootfs
  # layers at the same time. Faster hosts may override this value.
  COMPOSE_PARALLEL_LIMIT="${COMPOSE_UP_PARALLEL_LIMIT:-1}" \
    docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" up "$@"
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

ensure_zookeeper_service_root() {
  local output status
  set +e
  output="$({
    printf 'create /MDTService\nquit\n'
  } | docker exec -i \
    -e CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini \
    dc-saas-zookeeper \
    zkCli.sh -server "127.0.0.1:${ZOOKEEPER_PORT}" 2>&1)"
  status="$?"
  set -e

  if grep -Eq 'Created /MDTService|Node already exists: /MDTService' <<<"${output}"; then
    log "ZooKeeper service root /MDTService is ready."
    return 0
  fi

  printf '%s\n' "${output}" >&2
  die "Could not initialize /MDTService in ZooKeeper (exit ${status})."
}

wait_for_port() {
  local port="$1"
  local service_name="$2"
  local timeout_seconds="${3:-120}"
  local start
  start="$(date +%s)"

  until port_is_listening "${port}"; do
    if (( $(date +%s) - start >= timeout_seconds )); then
      docker logs --tail 100 "dc-saas-${service_name}" >&2 || true
      die "Timed out waiting for ${service_name} to listen on port ${port}."
    fi
    sleep 2
  done
  log "${service_name}: listening on ${port}"
}

apply_mysql_migrations() {
  local migration
  local migrations=()

  shopt -s nullglob
  migrations=("${SCRIPT_DIR}"/mysql/migrations/*.sql)
  shopt -u nullglob

  if (( ${#migrations[@]} == 0 )); then
    log "No MySQL migrations to apply."
    return 0
  fi

  for migration in "${migrations[@]}"; do
    log "Applying MySQL migration $(basename "${migration}")."
    docker exec -i \
      -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" \
      dc-saas-mysql \
      mysql --protocol=TCP -h127.0.0.1 -P"${MYSQL_PORT}" -uroot dc < "${migration}"
  done
}

provision_platform_admin() {
  [[ "${PLATFORM_ADMIN_USERNAME}" =~ ^[A-Za-z0-9_.@-]{3,64}$ ]] \
    || die "PLATFORM_ADMIN_USERNAME contains unsupported characters."
  [[ -n "${PLATFORM_ADMIN_PASSWORD}" && "${PLATFORM_ADMIN_PASSWORD}" != "replace-with-generated-secret" ]] \
    || die "PLATFORM_ADMIN_PASSWORD must be a generated secret."

  local password_hash
  password_hash="$(printf '%s' "${PLATFORM_ADMIN_PASSWORD}" | sha256sum | awk '{print $1}')"
  docker exec -i -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" dc-saas-mysql \
    mysql --protocol=TCP -h127.0.0.1 -P"${MYSQL_PORT}" -uroot dc <<SQL
INSERT INTO dc_users(user_id,user_name,name,password,user_type,enable,remark,create_time,update_time,
  enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES('${PLATFORM_ADMIN_USERNAME}','${PLATFORM_ADMIN_USERNAME}','Platform Administrator','${password_hash}',
  '1','1','SaaS platform operations',NOW(3),NOW(3),'0','0','0','deploy-saas','PLATFORM')
ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',update_time=NOW(3),close_by='deploy-saas';
SQL
  log "Platform administrator ${PLATFORM_ADMIN_USERNAME} provisioned for location PLATFORM."
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
validate_runtime_capacity
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
  compose_pull mysql clickhouse zookeeper
elif [[ "${IMAGE_SOURCE}" == "registry" ]]; then
  if [[ "${SKIP_PULL}" == "false" ]]; then
    log "Pulling SaaS application and infrastructure images."
    compose_pull
  fi
else
  die "IMAGE_SOURCE must be local or registry."
fi

log "Starting isolated MySQL, ClickHouse, and ZooKeeper."
compose_up -d mysql clickhouse zookeeper
wait_for_health dc-saas-mysql 420
wait_for_health dc-saas-clickhouse 420
wait_for_health dc-saas-zookeeper 120
ensure_zookeeper_service_root
apply_mysql_migrations
provision_platform_admin

log "Starting the SaaS application services and dc-trade-web."
compose_up -d
wait_for_health dc-saas-trade-web 300
wait_for_port "${GW_TCP_PORT}" gateway 120
wait_for_port "${LOGINSVR_GW_PORT}" loginsvr 120
wait_for_port "${LOGINSVR_HTTP_PORT}" loginsvr 180
wait_for_port "${MDSVR_GW_PORT}" mdsvr 120
wait_for_port "${APSSVR_GW_PORT}" apssvr 120
wait_for_port "${ORDERSVR_GW_PORT}" ordersvr 120
wait_for_port "${TRADESVR_GW_PORT}" tradesvr 120
wait_for_port "${LIQSVR_GW_PORT}" liqsvr 120
wait_for_port "${MANAGERSVR_GW_PORT}" managersvr 120
wait_for_port "${ADMINSVR_GW_PORT}" adminsvr 120

"${SCRIPT_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"
log "DC SaaS is ready at http://$(hostname -I | awk '{print $1}'):${WEB_LISTEN_PORT}/"
