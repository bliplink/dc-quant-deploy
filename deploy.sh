#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
CONTROL_SRC="${ROOT_DIR}/control.prod"
LAST_BACKUP_FILE="${ROOT_DIR}/.last_backup"
BACKUP_ROOT="${ROOT_DIR}/backups"
ZOOKEEPER_EXAMPLE_DIR="${ROOT_DIR}/zookeeper.example"

SERVICE_NAMES=(
  "tpc/Registry"
  "dc/GW/GW"
  "dc/MDSvr/MDSvr"
  "dc/APSSvr/APSSvr"
  "dc/QuantSvr/QuantSvr"
  "dc/INDSvr/INDSvr"
  "dc/SIMSvr/SIMSvr"
  "dc/BatchSvr/BatchSvr"
)
APP_SERVICES=(
  gateway
  mdsvr
  apssvr
  quantsvr
  indsvr
  simsvr
  batchsvr
  web
)
CLICKHOUSE_INIT_SCRIPT="${ROOT_DIR}/clickhouse/apply-init.sh"

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

check_file() {
  [ -f "$1" ] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

check_dir() {
  [ -d "$1" ] || {
    echo "Missing required directory: $1" >&2
    exit 1
  }
}

load_env() {
  check_file "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
  : "${CLICKHOUSE_MODE:?CLICKHOUSE_MODE is required}"
  : "${CLICKHOUSE_DB_NAME:?CLICKHOUSE_DB_NAME is required}"
  : "${CLICKHOUSE_HOST:?CLICKHOUSE_HOST is required}"
  : "${CLICKHOUSE_HTTP_PORT:?CLICKHOUSE_HTTP_PORT is required}"
  : "${CLICKHOUSE_IMAGE_TAG:?CLICKHOUSE_IMAGE_TAG is required}"
  : "${CLICKHOUSE_USERNAME:=default}"
  : "${CLICKHOUSE_PASSWORD:=}"
  case "${CLICKHOUSE_MODE}" in
    embedded|external) ;;
    *)
      echo "CLICKHOUSE_MODE must be embedded or external" >&2
      exit 1
      ;;
  esac
}

validate_ghcr_login() {
  local docker_config
  docker_config="${HOME}/.docker/config.json"
  check_file "${docker_config}"
  grep -q "ghcr.io" "${docker_config}" || {
    echo "GHCR login not found in ${docker_config}" >&2
    echo "Run: docker login ghcr.io" >&2
    exit 1
  }
}

validate_control_prod() {
  check_dir "${CONTROL_SRC}"
  check_file "${CONTROL_SRC}/ATSConfig.ini"
  check_file "${CONTROL_SRC}/DBPoolConfig.ini"
  check_file "${CONTROL_SRC}/jaas.ini"
  check_file "${CONTROL_SRC}/dc.dat"
}

prepare_runtime_dirs() {
  mkdir -p "${DEPLOY_ROOT}"
  mkdir -p "${DEPLOY_ROOT}/control"
  mkdir -p "${DEPLOY_ROOT}/data"
  mkdir -p "${DEPLOY_ROOT}/log"
  mkdir -p "${DEPLOY_ROOT}/tpc/zookeeper/conf"
  mkdir -p "${DEPLOY_ROOT}/tpc/zookeeper/data"
  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    mkdir -p "${DEPLOY_ROOT}/clickhouse/data"
    mkdir -p "${DEPLOY_ROOT}/clickhouse/log"
  fi
}

seed_zookeeper_runtime() {
  check_dir "${ZOOKEEPER_EXAMPLE_DIR}"
  check_file "${ZOOKEEPER_EXAMPLE_DIR}/conf/zoo.cfg"
  check_file "${ZOOKEEPER_EXAMPLE_DIR}/conf/jaas.conf"

  if [ ! -f "${DEPLOY_ROOT}/tpc/zookeeper/conf/zoo.cfg" ]; then
    cp "${ZOOKEEPER_EXAMPLE_DIR}/conf/zoo.cfg" "${DEPLOY_ROOT}/tpc/zookeeper/conf/zoo.cfg"
  fi

  if [ ! -f "${DEPLOY_ROOT}/tpc/zookeeper/conf/jaas.conf" ]; then
    cp "${ZOOKEEPER_EXAMPLE_DIR}/conf/jaas.conf" "${DEPLOY_ROOT}/tpc/zookeeper/conf/jaas.conf"
  fi
}

backup_control() {
  mkdir -p "${BACKUP_ROOT}"
  local timestamp backup_dir
  timestamp="$(date '+%Y%m%d_%H%M%S')"
  backup_dir="${BACKUP_ROOT}/control_${timestamp}"
  mkdir -p "${backup_dir}"

  if [ -d "${DEPLOY_ROOT}/control" ]; then
    cp -a "${DEPLOY_ROOT}/control" "${backup_dir}/control"
  fi

  printf '%s\n' "${backup_dir}" > "${LAST_BACKUP_FILE}"
  echo "Backup saved to ${backup_dir}"
}

record_status() {
  mkdir -p "${BACKUP_ROOT}"
  local snapshot_file
  snapshot_file="${BACKUP_ROOT}/status_$(date '+%Y%m%d_%H%M%S').log"
  if [ -x "${DEPLOY_ROOT}/scripts/show" ]; then
    "${DEPLOY_ROOT}/scripts/show" > "${snapshot_file}" 2>&1 || true
    echo "Current status written to ${snapshot_file}"
  fi
}

sync_control() {
  mkdir -p "${DEPLOY_ROOT}"
  rm -rf "${DEPLOY_ROOT}/control"
  mkdir -p "${DEPLOY_ROOT}/control"
  cp -a "${CONTROL_SRC}/." "${DEPLOY_ROOT}/control/"
}

stop_legacy_services() {
  if [ -x "${DEPLOY_ROOT}/scripts/stop" ]; then
    "${DEPLOY_ROOT}/scripts/stop" "${SERVICE_NAMES[@]}" || true
  fi
}

validate_port() {
  local label="$1"
  local host="$2"
  local port="$3"
  local retries="${4:-30}"
  local delay="${5:-2}"

  for _ in $(seq 1 "${retries}"); do
    if bash -c "exec 3<>/dev/tcp/${host}/${port}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "Port check failed for ${label} on ${host}:${port}" >&2
  return 1
}

clickhouse_http_query() {
  local sql="$1"
  curl --silent --show-error --fail \
    --user "${CLICKHOUSE_USERNAME}:${CLICKHOUSE_PASSWORD}" \
    --data-binary "${sql}" \
    "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_HTTP_PORT}/?database=${CLICKHOUSE_DB_NAME}"
}

wait_for_clickhouse_ready() {
  local retries="${1:-45}"
  local delay="${2:-2}"

  for _ in $(seq 1 "${retries}"); do
    if clickhouse_http_query "SELECT 1 FORMAT TSV" 2>/dev/null | grep -qx "1"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "ClickHouse readiness check failed." >&2
  return 1
}

apply_clickhouse_init() {
  check_file "${CLICKHOUSE_INIT_SCRIPT}"
  "${CLICKHOUSE_INIT_SCRIPT}"
}

wait_for_clickhouse_schema() {
  local expected_tables=3
  local retries="${1:-45}"
  local delay="${2:-2}"
  local sql="
    SELECT count()
    FROM system.tables
    WHERE database = '${CLICKHOUSE_DB_NAME}'
      AND name IN ('signal', 'quant_order', 'strategy_candidate')
    FORMAT TSV
  "

  for _ in $(seq 1 "${retries}"); do
    if clickhouse_http_query "${sql}" 2>/dev/null | grep -qx "${expected_tables}"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "ClickHouse schema readiness check failed." >&2
  return 1
}

validate_runtime() {
  validate_port "ClickHouse HTTP" "${CLICKHOUSE_HOST}" "${CLICKHOUSE_HTTP_PORT}"
  validate_port "ZooKeeper" 127.0.0.1 2181
  validate_port "gateway" 127.0.0.1 3002
  validate_port "MDSvr" 127.0.0.1 30028
  validate_port "APSSvr" 127.0.0.1 30035
  validate_port "QuantSvr" 127.0.0.1 30042
  validate_port "INDSvr" 127.0.0.1 30044
  validate_port "SIMSvr" 127.0.0.1 30045
  validate_port "BatchSvr" 127.0.0.1 30046
  validate_port "web" 127.0.0.1 80
}

main() {
  check_cmd docker
  check_cmd curl
  docker compose version >/dev/null
  load_env
  validate_ghcr_login
  validate_control_prod
  check_file "${COMPOSE_FILE}"
  prepare_runtime_dirs
  seed_zookeeper_runtime

  backup_control
  record_status
  sync_control
  stop_legacy_services

  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile embedded-clickhouse pull clickhouse zookeeper "${APP_SERVICES[@]}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile embedded-clickhouse up -d clickhouse zookeeper
  else
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull zookeeper "${APP_SERVICES[@]}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d zookeeper
  fi

  if ! wait_for_clickhouse_ready; then
    echo "ClickHouse is not reachable. Running rollback..." >&2
    "${ROOT_DIR}/rollback.sh"
    exit 1
  fi

  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    if ! apply_clickhouse_init; then
      echo "ClickHouse initialization failed. Running rollback..." >&2
      "${ROOT_DIR}/rollback.sh"
      exit 1
    fi
  fi

  if ! wait_for_clickhouse_schema; then
    if [[ "${CLICKHOUSE_MODE}" == "external" ]]; then
      echo "External ClickHouse schema is not ready. Initialize it manually first, then redeploy." >&2
    else
      echo "ClickHouse bootstrap did not complete. Running rollback..." >&2
    fi
    "${ROOT_DIR}/rollback.sh"
    exit 1
  fi

  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile embedded-clickhouse up -d "${APP_SERVICES[@]}"
  else
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d "${APP_SERVICES[@]}"
  fi

  if ! validate_runtime; then
    echo "Validation failed. Running rollback..." >&2
    "${ROOT_DIR}/rollback.sh"
    exit 1
  fi

  echo "Deployment completed successfully."
}

main "$@"
