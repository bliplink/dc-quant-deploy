#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
LOCK_FILE="${SAAS_AUTO_UPDATE_LOCK_FILE:-/tmp/dc-saas-auto-update.lock}"
SKIP_HOST_PREPARE="false"
SKIP_PULL="false"
ROBOT_IDENTITY_CHANGED="false"
LOGIN_CONTAINER_EXISTED="false"
SAAS_CHANGED_SERVICES="${SAAS_CHANGED_SERVICES:-}"

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

Deploy the DC cryptocurrency SaaS stack, optionally with OrderSvr and MDSvr
cluster profiles. This script never starts, stops, or reconfigures the
independent quantitative-trading stack.
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

ensure_generated_env_secret() {
  local key="$1"
  local current=""
  if grep -q "^${key}=" "${ENV_FILE}"; then
    current="$(sed -n "s/^${key}=//p" "${ENV_FILE}" | tail -n 1)"
  fi
  if [[ -n "${current}" && "${current}" != "replace-with-generated-secret" ]]; then
    return 0
  fi
  if grep -q "^${key}=" "${ENV_FILE}"; then
    set_env_value "${key}" "$(generate_secret)"
  else
    printf '%s=%s\n' "${key}" "$(generate_secret)" >> "${ENV_FILE}"
  fi
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
  set_env_value DC_HEDGE_CREDENTIAL_MASTER_KEY "$(generate_secret)"
  set_env_value ROBOT_RUNTIME_API_KEY "$(generate_secret)"
  set_env_value ROBOT_RUNTIME_API_SECRET "$(generate_secret)"
  log "Created ${ENV_FILE} with generated local secrets."
}

ensure_env_defaults() {
  if ! grep -q '^IMAGE_SOURCE=' "${ENV_FILE}"; then
    printf '\nIMAGE_SOURCE=registry\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^BUILD_ROOT=' "${ENV_FILE}"; then
    printf 'BUILD_ROOT=/data/dc-saas-build\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDER_CLUSTER_ENABLED=' "${ENV_FILE}"; then
    printf 'ORDER_CLUSTER_ENABLED=false\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDER_CLUSTER_C_ENABLED=' "${ENV_FILE}"; then
    printf 'ORDER_CLUSTER_C_ENABLED=false\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^MD_CLUSTER_ENABLED=' "${ENV_FILE}"; then
    printf 'MD_CLUSTER_ENABLED=false\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^MDSVR_B_GW_PORT=' "${ENV_FILE}"; then
    printf 'MDSVR_B_GW_PORT=33043\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDERSVR_B_GW_PORT=' "${ENV_FILE}"; then
    printf 'ORDERSVR_B_GW_PORT=33041\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDERSVR_C_GW_PORT=' "${ENV_FILE}"; then
    printf 'ORDERSVR_C_GW_PORT=33044\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDERSVR_A_REPLICATION_PORT=' "${ENV_FILE}"; then
    printf 'ORDERSVR_A_REPLICATION_PORT=19121\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDERSVR_B_REPLICATION_PORT=' "${ENV_FILE}"; then
    printf 'ORDERSVR_B_REPLICATION_PORT=19122\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDERSVR_C_REPLICATION_PORT=' "${ENV_FILE}"; then
    printf 'ORDERSVR_C_REPLICATION_PORT=19123\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED=' "${ENV_FILE}"; then
    printf 'ORDER_CLUSTER_PERIODIC_SNAPSHOT_ENABLED=true\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^PROJECTIONSVR_GW_PORT=' "${ENV_FILE}"; then
    printf 'PROJECTIONSVR_GW_PORT=33042\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^PLATFORM_ADMIN_USERNAME=' "${ENV_FILE}"; then
    printf 'PLATFORM_ADMIN_USERNAME=platformadmin\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^PLATFORM_ADMIN_PASSWORD=' "${ENV_FILE}"; then
    printf 'PLATFORM_ADMIN_PASSWORD=%s\n' "$(generate_secret)" >> "${ENV_FILE}"
  fi
  if ! grep -q '^DC_HEDGE_CREDENTIAL_MASTER_KEY=' "${ENV_FILE}"; then
    printf 'DC_HEDGE_CREDENTIAL_MASTER_KEY=%s\n' "$(generate_secret)" >> "${ENV_FILE}"
  fi
  if ! grep -q '^ROBOT_RUNTIME_LOCATION=' "${ENV_FILE}"; then
    printf 'ROBOT_RUNTIME_LOCATION=PLATFORM\n' >> "${ENV_FILE}"
  fi
  if ! grep -q '^ROBOT_RUNTIME_USER_ID=' "${ENV_FILE}"; then
    printf 'ROBOT_RUNTIME_USER_ID=robotsvr\n' >> "${ENV_FILE}"
  fi
  ensure_generated_env_secret ROBOT_RUNTIME_API_KEY
  ensure_generated_env_secret ROBOT_RUNTIME_API_SECRET
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
  if grep -q '^TRADESVR_TAG=sha-' "${ENV_FILE}"; then
    sed -i 's/^TRADESVR_TAG=sha-.*/TRADESVR_TAG=saas-crypto/' "${ENV_FILE}"
  fi
  # Public application images use the moving saas-crypto tag so the
  # digest-based updater can detect each newly published Web build. Migrate
  # every historical source/CI pin instead of maintaining an ever-growing
  # release-specific allow-list.
  if grep -Eq '^TRADE_WEB_TAG=(source-|sha-)' "${ENV_FILE}"; then
    sed -i 's/^TRADE_WEB_TAG=.*/TRADE_WEB_TAG=saas-crypto/' "${ENV_FILE}"
  fi
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

  local profiles=()
  if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
    profiles+=(order-cluster)
    export ORDERSVR_CONFIG_NAME=OrderSvrA
    if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
      profiles+=(order-cluster-c)
    fi
  else
    export ORDERSVR_CONFIG_NAME=OrderSvr
  fi
  if [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]]; then
    profiles+=(md-cluster)
    export MDSVR_CONFIG_NAME=MDSvrA
  else
    export MDSVR_CONFIG_NAME=MDSvr
  fi
  export COMPOSE_PROFILES="$(IFS=,; printf '%s' "${profiles[*]}")"
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

  local ports=("${MYSQL_PORT}" "${CLICKHOUSE_HTTP_PORT}" "${CLICKHOUSE_NATIVE_PORT}" "${ZOOKEEPER_PORT}" "${ZOOKEEPER_JMX_PORT}" "${GW_TCP_PORT}" "${GW_WEBSOCKET_PORT}" "${GW_HTTP_PORT}" "${LOGINSVR_HTTP_PORT}" "${LOGINSVR_GW_PORT}" "${MDSVR_GW_PORT}" "${APSSVR_GW_PORT}" "${ORDERSVR_GW_PORT}" "${PROJECTIONSVR_GW_PORT:-33042}" "${TRADESVR_GW_PORT}" "${LIQSVR_GW_PORT}" "${MANAGERSVR_GW_PORT}" "${ADMINSVR_GW_PORT}" "${WEB_LISTEN_PORT}")
  if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
    ports+=("${ORDERSVR_B_GW_PORT}" "${ORDERSVR_A_REPLICATION_PORT}" "${ORDERSVR_B_REPLICATION_PORT}")
    if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
      ports+=("${ORDERSVR_C_GW_PORT}" "${ORDERSVR_C_REPLICATION_PORT}")
    fi
  fi
  if [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]]; then
    ports+=("${MDSVR_B_GW_PORT}")
  fi
  for port in "${ports[@]}"; do
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

require_immutable_cluster_image() {
  local name="$1" image="$2" tag="${2##*:}"
  case "${tag}" in
    cluster-dev-*|sha-*) return 0 ;;
    *) die "${name} must use an immutable cluster image: ${image}" ;;
  esac
}

verify_order_cluster_images() {
  [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local expected_hash="" expected_revision="" spec name image hash revision
  local specs=(
    "gateway|${GW_IMAGE_REPOSITORY}:${GW_TAG}"
    "ordersvr|${ORDERSVR_IMAGE_REPOSITORY}:${ORDERSVR_TAG}"
  )
  for spec in "${specs[@]}"; do
    name="${spec%%|*}"
    image="${spec#*|}"
    require_immutable_cluster_image "${name}" "${image}"
    hash="$(docker image inspect "${image}" --format '{{index .Config.Labels "dc.common.jar.sha256"}}' 2>/dev/null || true)"
    revision="$(docker image inspect "${image}" --format '{{index .Config.Labels "dc.common.revision"}}' 2>/dev/null || true)"
    [[ "${hash}" =~ ^[0-9a-f]{64}$ ]] || die "${name} cluster image has no Common SHA-256 label: ${image}"
    [[ -n "${revision}" && "${revision}" != "unknown" ]] || die "${name} cluster image has no Common revision label: ${image}"
    if [[ -z "${expected_hash}" ]]; then
      expected_hash="${hash}"
      expected_revision="${revision}"
    else
      [[ "${hash}" == "${expected_hash}" ]] || die "${name} embeds a different Common JAR."
      [[ "${revision}" == "${expected_revision}" ]] || die "${name} embeds a different Common revision."
    fi
  done
  log "Cluster image identity verified: Common ${expected_revision}, SHA-256 ${expected_hash}."
}

verify_md_cluster_images() {
  [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local expected_hash="" expected_revision="" spec name image hash revision
  local specs=(
    "gateway|${GW_IMAGE_REPOSITORY}:${GW_TAG}"
    "mdsvr|${MDSVR_IMAGE_REPOSITORY}:${MDSVR_TAG}"
  )
  for spec in "${specs[@]}"; do
    name="${spec%%|*}"
    image="${spec#*|}"
    require_immutable_cluster_image "${name}" "${image}"
    hash="$(docker image inspect "${image}" --format '{{index .Config.Labels "dc.common.jar.sha256"}}' 2>/dev/null || true)"
    revision="$(docker image inspect "${image}" --format '{{index .Config.Labels "dc.common.revision"}}' 2>/dev/null || true)"
    [[ "${hash}" =~ ^[0-9a-f]{64}$ ]] || die "${name} cluster image has no Common SHA-256 label: ${image}"
    [[ -n "${revision}" && "${revision}" != "unknown" ]] || die "${name} cluster image has no Common revision label: ${image}"
    if [[ -z "${expected_hash}" ]]; then
      expected_hash="${hash}"
      expected_revision="${revision}"
    else
      [[ "${hash}" == "${expected_hash}" ]] || die "${name} embeds a different Common JAR."
      [[ "${revision}" == "${expected_revision}" ]] || die "${name} embeds a different Common revision."
    fi
  done
  log "MD cluster image identity verified: Common ${expected_revision}, SHA-256 ${expected_hash}."
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

ensure_order_cluster_assignments() {
  [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local commands output status count partition node replica
  commands="$(mktemp)"
  {
    printf 'create /dc x\n'
    printf 'create /dc/cluster x\n'
    printf 'create /dc/cluster/ordersvr x\n'
    printf 'create /dc/cluster/ordersvr/partitions x\n'
    for ((partition=0; partition<256; partition++)); do
      if (( partition % 2 == 0 )); then
        node=OrderSvrA
        replica=OrderSvrB
      else
        node=OrderSvrB
        replica=OrderSvrA
      fi
      printf 'create /dc/cluster/ordersvr/partitions/P%03d {"partitionId":"P%03d","epoch":1,"primary":"%s","replica":"%s","state":"READY"}\n' \
        "${partition}" "${partition}" "${node}" "${replica}"
    done
    printf 'quit\n'
  } > "${commands}"
  set +e
  output="$(docker exec -i \
    -e CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini \
    dc-saas-zookeeper zkCli.sh -server "127.0.0.1:${ZOOKEEPER_PORT}" < "${commands}" 2>&1)"
  status="$?"
  set -e
  rm -f -- "${commands}"
  if grep -Eq 'KeeperErrorCode = (NoAuth|InvalidACL|ConnectionLoss|SessionExpired)' <<<"${output}"; then
    printf '%s\n' "${output}" >&2
    die "Could not initialize OrderSvr partition assignments (exit ${status})."
  fi
  # zkCli exits with code 1 when any create command encounters NodeExists.
  # Re-running deployment against an initialized cluster is expected to hit
  # that condition, so rely on the authoritative child-count check below.
  if (( status != 0 )) && ! grep -Fq 'Node already exists:' <<<"${output}"; then
    printf '%s\n' "${output}" >&2
    die "Could not initialize OrderSvr partition assignments (exit ${status})."
  fi
  output="$({ printf 'ls /dc/cluster/ordersvr/partitions\nquit\n'; } | docker exec -i \
    -e CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini \
    dc-saas-zookeeper zkCli.sh -server "127.0.0.1:${ZOOKEEPER_PORT}" 2>&1)"
  count="$(grep -oE 'P[0-9]{3}' <<<"${output}" | sort -u | wc -l | tr -d ' ')"
  [[ "${count}" == "256" ]] || die "Expected 256 OrderSvr assignments, found ${count}."
  log "ZooKeeper OrderSvr assignments are ready: 256 partitions, alternating A/B primaries."
}

ensure_md_cluster_assignments() {
  [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local commands output status count partition node replica
  commands="$(mktemp)"
  {
    printf 'create /dc x\n'
    printf 'create /dc/cluster x\n'
    printf 'create /dc/cluster/mdsvr x\n'
    printf 'create /dc/cluster/mdsvr/partitions x\n'
    for ((partition=0; partition<256; partition++)); do
      if (( partition % 2 == 0 )); then
        node=MDSvrA
        replica=MDSvrB
      else
        node=MDSvrB
        replica=MDSvrA
      fi
      printf 'create /dc/cluster/mdsvr/partitions/P%03d {"partitionId":"P%03d","epoch":1,"primary":"%s","replica":"%s","state":"READY"}\n' \
        "${partition}" "${partition}" "${node}" "${replica}"
    done
    printf 'quit\n'
  } > "${commands}"
  set +e
  output="$(docker exec -i \
    -e CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini \
    dc-saas-zookeeper zkCli.sh -server "127.0.0.1:${ZOOKEEPER_PORT}" < "${commands}" 2>&1)"
  status="$?"
  set -e
  rm -f -- "${commands}"
  if grep -Eq 'KeeperErrorCode = (NoAuth|InvalidACL|ConnectionLoss|SessionExpired)' <<<"${output}"; then
    printf '%s\n' "${output}" >&2
    die "Could not initialize MDSvr partition assignments (exit ${status})."
  fi
  if (( status != 0 )) && ! grep -Fq 'Node already exists:' <<<"${output}"; then
    printf '%s\n' "${output}" >&2
    die "Could not initialize MDSvr partition assignments (exit ${status})."
  fi
  output="$({ printf 'ls /dc/cluster/mdsvr/partitions\nquit\n'; } | docker exec -i \
    -e CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini \
    dc-saas-zookeeper zkCli.sh -server "127.0.0.1:${ZOOKEEPER_PORT}" 2>&1)"
  count="$(grep -oE 'P[0-9]{3}' <<<"${output}" | sort -u | wc -l | tr -d ' ')"
  [[ "${count}" == "256" ]] || die "Expected 256 MDSvr assignments, found ${count}."
  log "ZooKeeper MDSvr assignments are ready: 256 partitions, alternating A/B primaries."
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

wait_for_order_cluster_readiness() {
  [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local start count
  start="$(date +%s)"
  while true; do
    count="$(current_order_cluster_ready_count)"
    if [[ "${count}" == "256" ]]; then
      log "OrderSvr cluster readiness complete: 256/256 partitions."
      return 0
    fi
    if (( $(date +%s) - start >= 300 )); then
      docker logs --tail 100 dc-saas-ordersvr >&2 || true
      docker logs --tail 100 dc-saas-ordersvr-b >&2 || true
      if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
        docker logs --tail 100 dc-saas-ordersvr-c >&2 || true
      fi
      die "Timed out waiting for OrderSvr cluster readiness: ${count:-0}/256 partitions."
    fi
    sleep 2
  done
}

current_order_cluster_ready_count() {
  local a_started b_started c_started=""
  a_started="$(docker inspect --format '{{.State.StartedAt}}' dc-saas-ordersvr 2>/dev/null || true)"
  b_started="$(docker inspect --format '{{.State.StartedAt}}' dc-saas-ordersvr-b 2>/dev/null || true)"
  if [[ -z "${a_started}" || -z "${b_started}" ]]; then
    printf '0\n'
    return 0
  fi
  if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    c_started="$(docker inspect --format '{{.State.StartedAt}}' dc-saas-ordersvr-c 2>/dev/null || true)"
    if [[ -z "${c_started}" ]]; then
      printf '0\n'
      return 0
    fi
  fi
  {
    docker logs --since "${a_started}" dc-saas-ordersvr 2>&1 || true
    docker logs --since "${b_started}" dc-saas-ordersvr-b 2>&1 || true
    if [[ -n "${c_started}" ]]; then
      docker logs --since "${c_started}" dc-saas-ordersvr-c 2>&1 || true
    fi
  } | awk '
    /ORDER_PARTITION_(BOOTSTRAP|PROMOTION)_READY/ {
      if (match($0, /partition:P[0-9][0-9][0-9]/)) print substr($0, RSTART + 10, 4)
    }
  ' | sort -u | wc -l | tr -d ' '
}

recover_order_cluster_if_needed() {
  [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]] || return 0
  local count attempt recovery_script
  recovery_script="${SCRIPT_DIR}/tests/recover-order-cluster-partitions-host.sh"
  [[ -x "${recovery_script}" ]] || die "Missing executable OrderSvr recovery script: ${recovery_script}"

  # A brand-new empty cluster may finish its bootstrap without an epoch change.
  # Give that path a short window, but do not accept READY lines retained from a
  # prior process incarnation after Docker restarts a failed JVM.
  for attempt in $(seq 1 15); do
    count="$(current_order_cluster_ready_count)"
    [[ "${count}" == "256" ]] && {
      log "OrderSvr A/B are already ready in the current container incarnations."
      return 0
    }
    sleep 2
  done

  log "OrderSvr A/B current-incarnation readiness is ${count:-0}/256; starting staged epoch recovery."
  ORDER_CLUSTER_ZK_SERVER="127.0.0.1:${ZOOKEEPER_PORT}" "${recovery_script}"
}

gateway_routes_need_refresh() {
  local service
  # A direct/manual deployment has no changed-service manifest, so choose the
  # safe full-deploy behavior. The auto updater supplies the exact set and can
  # skip a needless GW restart for a Web-only release.
  [[ -n "${SAAS_CHANGED_SERVICES}" ]] || return 0
  for service in loginsvr mdsvr apssvr ordersvr projectionsvr tradesvr liqsvr managersvr adminsvr robotsvr; do
    [[ " ${SAAS_CHANGED_SERVICES} " == *" ${service} "* ]] && return 0
  done
  return 1
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

provision_robot_runtime_identity() {
  [[ "${ROBOT_RUNTIME_LOCATION}" =~ ^[A-Za-z0-9_.@-]{1,64}$ ]] \
    || die "ROBOT_RUNTIME_LOCATION contains unsupported characters."
  [[ "${ROBOT_RUNTIME_USER_ID}" =~ ^[A-Za-z0-9_.@-]{3,45}$ ]] \
    || die "ROBOT_RUNTIME_USER_ID contains unsupported characters."
  [[ "${ROBOT_RUNTIME_API_KEY}" =~ ^[A-Za-z0-9]{32,64}$ ]] \
    || die "ROBOT_RUNTIME_API_KEY must contain 32-64 alphanumeric characters."
  [[ "${ROBOT_RUNTIME_API_SECRET}" =~ ^[A-Za-z0-9]{32,64}$ ]] \
    || die "ROBOT_RUNTIME_API_SECRET must contain 32-64 alphanumeric characters."

  local password_hash identity_count
  password_hash="$(printf '%s' "${ROBOT_RUNTIME_API_SECRET}" | sha256sum | awk '{print $1}')"
  identity_count="$(docker exec -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" dc-saas-mysql \
    mysql --protocol=TCP -h127.0.0.1 -P"${MYSQL_PORT}" -uroot -N dc -e \
    "SELECT COUNT(*) FROM dc_users_api WHERE location='${ROBOT_RUNTIME_LOCATION}' \
      AND user_id='${ROBOT_RUNTIME_USER_ID}' AND api_key='${ROBOT_RUNTIME_API_KEY}' \
      AND secret_key='${ROBOT_RUNTIME_API_SECRET}' AND enable='1';")"
  [[ "${identity_count}" == "1" ]] || ROBOT_IDENTITY_CHANGED="true"
  docker exec -i -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" dc-saas-mysql \
    mysql --protocol=TCP -h127.0.0.1 -P"${MYSQL_PORT}" -uroot dc <<SQL
INSERT INTO dc_users(user_id,user_name,name,password,user_type,enable,remark,create_time,update_time,
  enable_trade,enable_cash_in,enable_cash_out,close_by,location)
VALUES('${ROBOT_RUNTIME_USER_ID}','${ROBOT_RUNTIME_USER_ID}','Robot Runtime','${password_hash}',
  '1','1','Internal GW-only Robot runtime',NOW(3),NOW(3),'0','0','0','deploy-saas','${ROBOT_RUNTIME_LOCATION}')
ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',update_time=NOW(3),close_by='deploy-saas';
UPDATE dc_users_api SET enable='0',update_time=DATE_FORMAT(NOW(3),'%Y-%m-%d %H:%i:%s.%f'),close_by='deploy-saas'
WHERE location='${ROBOT_RUNTIME_LOCATION}' AND user_id='${ROBOT_RUNTIME_USER_ID}'
  AND api_key<>'${ROBOT_RUNTIME_API_KEY}';
INSERT INTO dc_users_api(user_id,type,api_key,secret_key,enable,create_time,update_time,close_by,inf1,location)
VALUES('${ROBOT_RUNTIME_USER_ID}','ROBOT_RUNTIME','${ROBOT_RUNTIME_API_KEY}','${ROBOT_RUNTIME_API_SECRET}',
  '1',DATE_FORMAT(NOW(3),'%Y-%m-%d %H:%i:%s.%f'),DATE_FORMAT(NOW(3),'%Y-%m-%d %H:%i:%s.%f'),
  'deploy-saas','GW-only Robot runtime','${ROBOT_RUNTIME_LOCATION}')
ON DUPLICATE KEY UPDATE secret_key=VALUES(secret_key),enable='1',update_time=VALUES(update_time),
  close_by='deploy-saas',location=VALUES(location);
SQL
  log "Dedicated Robot runtime identity ${ROBOT_RUNTIME_LOCATION}/${ROBOT_RUNTIME_USER_ID} provisioned."
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
verify_order_cluster_images
verify_md_cluster_images

if docker inspect dc-saas-loginsvr >/dev/null 2>&1; then
  LOGIN_CONTAINER_EXISTED="true"
fi

log "Starting isolated MySQL, ClickHouse, and ZooKeeper."
compose_up -d mysql clickhouse zookeeper
wait_for_health dc-saas-mysql 420
wait_for_health dc-saas-clickhouse 420
wait_for_health dc-saas-zookeeper 120
  ensure_zookeeper_service_root
  ensure_order_cluster_assignments
  ensure_md_cluster_assignments
apply_mysql_migrations
provision_platform_admin
provision_robot_runtime_identity

log "Starting the SaaS application services and dc-trade-web."
compose_up -d
# ApiKeyService loads its in-memory key map when LoginSvr starts.  Restart it
# only when provisioning actually changed the Robot credential.  The previous
# pre-compose force-recreate made the following full `compose up` recreate the
# same host-network container a second time and could race its released HTTP
# port on slower production hosts.
if [[ "${ROBOT_IDENTITY_CHANGED}" == "true" && "${LOGIN_CONTAINER_EXISTED}" == "true" ]]; then
  log "Robot runtime identity changed; restarting LoginSvr once to reload API keys."
  docker restart dc-saas-loginsvr >/dev/null
fi
wait_for_health dc-saas-trade-web 300
wait_for_port "${GW_TCP_PORT}" gateway 120
wait_for_port "${LOGINSVR_GW_PORT}" loginsvr 120
wait_for_port "${LOGINSVR_HTTP_PORT}" loginsvr 180
wait_for_port "${MDSVR_GW_PORT}" mdsvr 120
if [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]]; then
  wait_for_port "${MDSVR_B_GW_PORT}" mdsvr-b 180
fi
wait_for_port "${APSSVR_GW_PORT}" apssvr 120
wait_for_port "${ORDERSVR_GW_PORT}" ordersvr 120
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
  wait_for_port "${ORDERSVR_B_GW_PORT}" ordersvr-b 180
  wait_for_port "${ORDERSVR_A_REPLICATION_PORT}" ordersvr 180
  wait_for_port "${ORDERSVR_B_REPLICATION_PORT}" ordersvr-b 180
  if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    wait_for_port "${ORDERSVR_C_GW_PORT}" ordersvr-c 180
    wait_for_port "${ORDERSVR_C_REPLICATION_PORT}" ordersvr-c 180
  fi
fi
recover_order_cluster_if_needed
wait_for_order_cluster_readiness
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
  wait_for_port "${PROJECTIONSVR_GW_PORT:-33042}" projectionsvr 120
fi
wait_for_port "${TRADESVR_GW_PORT}" tradesvr 120
wait_for_port "${LIQSVR_GW_PORT}" liqsvr 120
wait_for_port "${MANAGERSVR_GW_PORT}" managersvr 120
wait_for_port "${ADMINSVR_GW_PORT}" adminsvr 120

# GW caches both service aliases (for example TDSvr) and direct instance
# names (TradeSvr). A backend container recreation can change its host-network
# registration before both cache entries converge. Refresh only after every
# backend listener is ready, then validate both names through the public API.
if gateway_routes_need_refresh; then
  log "Backend services changed; refreshing GW service and alias routes."
  docker restart dc-saas-gateway >/dev/null
  wait_for_port "${GW_TCP_PORT}" gateway 120
fi

"${SCRIPT_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"
log "DC SaaS is ready at http://$(hostname -I | awk '{print $1}'):${WEB_LISTEN_PORT}/"
