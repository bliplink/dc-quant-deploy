#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${ROOT_DIR}/generate-compose-overrides.sh"
CONTROL_SRC="${ROOT_DIR}/control.prod"
LAST_BACKUP_FILE="${ROOT_DIR}/.last_backup"
BACKUP_ROOT="${ROOT_DIR}/backups"

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
TARGETABLE_SERVICES=(
  gateway
  loginsvr
  mdsvr
  apssvr
  quantsvr
  indsvr
  simsvr
  batchsvr
  web
)
DEPLOY_MODE="full"
DEPLOY_SERVICES=()
CLICKHOUSE_INIT_SCRIPT="${ROOT_DIR}/clickhouse/apply-init.sh"

usage() {
  cat <<'USAGE'
Usage:
  ./deploy.sh
  ./deploy.sh --services SERVICE[,SERVICE...]

Without --services, deploy the complete stack.

With --services, initialize shared runtime files and deploy only the selected
application containers with --no-deps. Local ZooKeeper and ClickHouse are not
started in this mode; configure their reachable addresses before deployment.

Supported service names:
  gateway, loginsvr, mdsvr, apssvr, quantsvr, indsvr, simsvr, batchsvr, web

Example:
  ./deploy.sh --services apssvr,quantsvr
USAGE
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -f "${OVERRIDE_FILE}" "$@"
}

contains_service() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [[ "${item}" == "${needle}" ]]; then
      return 0
    fi
  done
  return 1
}

normalize_service() {
  case "$1" in
    GW|gw)
      printf 'gateway\n'
      ;;
    gateway|loginsvr|mdsvr|apssvr|quantsvr|indsvr|simsvr|batchsvr|web)
      printf '%s\n' "$1"
      ;;
    *)
      printf '\n'
      ;;
  esac
}

append_deploy_service() {
  local service="$1"
  if ! contains_service "${service}" "${DEPLOY_SERVICES[@]:-}"; then
    DEPLOY_SERVICES+=("${service}")
  fi
}

parse_args() {
  local raw_services raw normalized
  local -a requested=()

  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --services)
        shift
        [[ "$#" -gt 0 ]] || {
          echo "--services requires a comma-separated value." >&2
          exit 1
        }
        DEPLOY_MODE="selected"
        raw_services="$1"
        IFS=',' read -r -a requested <<< "${raw_services}"
        for raw in "${requested[@]}"; do
          normalized="$(normalize_service "${raw}")"
          if [[ -z "${normalized}" ]] ||
             ! contains_service "${normalized}" "${TARGETABLE_SERVICES[@]}"; then
            echo "Unsupported service: ${raw}" >&2
            usage >&2
            exit 1
          fi
          append_deploy_service "${normalized}"
        done
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done

  if [[ "${DEPLOY_MODE}" == "full" ]]; then
    DEPLOY_SERVICES=("${APP_SERVICES[@]}")
  elif [[ "${#DEPLOY_SERVICES[@]}" -eq 0 ]]; then
    echo "No deployable services were selected." >&2
    exit 1
  fi
}

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
  : "${RUNTIME_UID:?RUNTIME_UID is required}"
  : "${RUNTIME_GID:?RUNTIME_GID is required}"
  : "${CLICKHOUSE_MODE:?CLICKHOUSE_MODE is required}"
  : "${CLICKHOUSE_DB_NAME:?CLICKHOUSE_DB_NAME is required}"
  : "${CLICKHOUSE_HOST:?CLICKHOUSE_HOST is required}"
  : "${CLICKHOUSE_HTTP_PORT:?CLICKHOUSE_HTTP_PORT is required}"
  : "${CLICKHOUSE_IMAGE_TAG:?CLICKHOUSE_IMAGE_TAG is required}"
  : "${CLICKHOUSE_USERNAME:=default}"
  : "${CLICKHOUSE_PASSWORD:=}"
  [[ "${RUNTIME_UID}" =~ ^[0-9]+$ ]] || {
    echo "RUNTIME_UID must be numeric." >&2
    exit 1
  }
  [[ "${RUNTIME_GID}" =~ ^[0-9]+$ ]] || {
    echo "RUNTIME_GID must be numeric." >&2
    exit 1
  }
  case "${CLICKHOUSE_MODE}" in
    embedded|external) ;;
    *)
      echo "CLICKHOUSE_MODE must be embedded or external" >&2
      exit 1
      ;;
  esac
}

check_system_requirements() {
  local min_mem_mb min_disk_gb mem_mb disk_mb disk_gb
  min_mem_mb="${MIN_MEMORY_MB:-8192}"
  min_disk_gb="${MIN_DISK_GB:-20}"

  mem_mb="$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null || echo 0)"

  mkdir -p "${DEPLOY_ROOT}"
  disk_mb="$(df -Pm "${DEPLOY_ROOT}" | awk 'NR==2 {print $4}')"
  disk_gb="$((disk_mb / 1024))"

  if [ "${mem_mb}" -lt "${min_mem_mb}" ]; then
    echo "Machine check failed: memory ${mem_mb} MB, required >= ${min_mem_mb} MB." >&2
    exit 1
  fi

  if [ "${disk_gb}" -lt "${min_disk_gb}" ]; then
    echo "Machine check failed: free disk ${disk_gb} GB at ${DEPLOY_ROOT}, required >= ${min_disk_gb} GB." >&2
    exit 1
  fi
}

validate_ghcr_login() {
  local docker_config
  docker_config="${HOME}/.docker/config.json"
  if [ -f "${docker_config}" ] && grep -q "ghcr.io" "${docker_config}"; then
    return 0
  fi

  if [[ "${REQUIRE_GHCR_LOGIN:-false}" == "true" ]]; then
    echo "GHCR login not found in ${docker_config}" >&2
    echo "Run: docker login ghcr.io" >&2
    exit 1
  fi

  echo "Warning: GHCR login not found in ${docker_config}; continuing because REQUIRE_GHCR_LOGIN is not true." >&2
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
  mkdir -p "${DEPLOY_ROOT}/control/overrides"
  mkdir -p "${DEPLOY_ROOT}/data"
  mkdir -p "${DEPLOY_ROOT}/data/zookeeper"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/GW"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/LoginSvr"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/MDSvr"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/APSSvr"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/QuantSvr"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/INDSvr"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/SIMSvr"
  mkdir -p "${DEPLOY_ROOT}/data/java-prefs/BatchSvr"
  mkdir -p "${DEPLOY_ROOT}/log"
  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    mkdir -p "${DEPLOY_ROOT}/data/clickhouse"
    mkdir -p "${DEPLOY_ROOT}/log/clickhouse"
  fi

  chown "${RUNTIME_UID}:${RUNTIME_GID}" \
    "${DEPLOY_ROOT}/data" \
    "${DEPLOY_ROOT}/log" \
    "${DEPLOY_ROOT}/data/java-prefs/GW" \
    "${DEPLOY_ROOT}/data/java-prefs/LoginSvr" \
    "${DEPLOY_ROOT}/data/java-prefs/MDSvr" \
    "${DEPLOY_ROOT}/data/java-prefs/APSSvr" \
    "${DEPLOY_ROOT}/data/java-prefs/QuantSvr" \
    "${DEPLOY_ROOT}/data/java-prefs/INDSvr" \
    "${DEPLOY_ROOT}/data/java-prefs/SIMSvr" \
    "${DEPLOY_ROOT}/data/java-prefs/BatchSvr"
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
  local preserved_overrides
  preserved_overrides="$(mktemp -d)"

  if [ -d "${DEPLOY_ROOT}/control/overrides" ]; then
    cp -a "${DEPLOY_ROOT}/control/overrides" "${preserved_overrides}/overrides"
  fi

  mkdir -p "${DEPLOY_ROOT}"
  rm -rf "${DEPLOY_ROOT}/control"
  mkdir -p "${DEPLOY_ROOT}/control"

  find "${CONTROL_SRC}" -mindepth 1 -maxdepth 1 ! -name overrides -exec cp -a {} "${DEPLOY_ROOT}/control/" \;

  if [ -d "${preserved_overrides}/overrides" ]; then
    cp -a "${preserved_overrides}/overrides" "${DEPLOY_ROOT}/control/overrides"
  else
    mkdir -p "${DEPLOY_ROOT}/control/overrides"
  fi

  rm -rf "${preserved_overrides}"
}

generate_compose_overrides() {
  check_file "${GENERATE_OVERRIDES_SCRIPT}"
  bash "${GENERATE_OVERRIDES_SCRIPT}" "${ENV_FILE}" "${OVERRIDE_FILE}"
}

stop_legacy_services() {
  local legacy_services=()

  if [[ "${DEPLOY_MODE}" == "full" ]]; then
    legacy_services=("${SERVICE_NAMES[@]}")
  else
    local service
    for service in "${DEPLOY_SERVICES[@]}"; do
      case "${service}" in
        gateway) legacy_services+=("dc/GW/GW") ;;
        mdsvr) legacy_services+=("dc/MDSvr/MDSvr") ;;
        apssvr) legacy_services+=("dc/APSSvr/APSSvr") ;;
        quantsvr) legacy_services+=("dc/QuantSvr/QuantSvr") ;;
        indsvr) legacy_services+=("dc/INDSvr/INDSvr") ;;
        simsvr) legacy_services+=("dc/SIMSvr/SIMSvr") ;;
        batchsvr) legacy_services+=("dc/BatchSvr/BatchSvr") ;;
      esac
    done
  fi

  if [ -x "${DEPLOY_ROOT}/scripts/stop" ]; then
    if [[ "${#legacy_services[@]}" -gt 0 ]]; then
      "${DEPLOY_ROOT}/scripts/stop" "${legacy_services[@]}" || true
    fi
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

validate_service_port() {
  local service="$1"
  case "${service}" in
    gateway) validate_port "gateway" "${SERVICE_HOST:-127.0.0.1}" 3002 ;;
    loginsvr) validate_port "LoginSvr" "${SERVICE_HOST:-127.0.0.1}" 30022 ;;
    mdsvr) validate_port "MDSvr" "${SERVICE_HOST:-127.0.0.1}" 30028 ;;
    apssvr) validate_port "APSSvr" "${SERVICE_HOST:-127.0.0.1}" 30035 ;;
    quantsvr) validate_port "QuantSvr" "${SERVICE_HOST:-127.0.0.1}" 30042 ;;
    indsvr) validate_port "INDSvr" "${SERVICE_HOST:-127.0.0.1}" 30044 ;;
    simsvr) validate_port "SIMSvr" "${SERVICE_HOST:-127.0.0.1}" 30045 ;;
    batchsvr) validate_port "BatchSvr" "${SERVICE_HOST:-127.0.0.1}" 30046 ;;
    web) validate_port "web" "${SERVICE_HOST:-127.0.0.1}" 80 ;;
    *)
      echo "No validation rule for service: ${service}" >&2
      return 1
      ;;
  esac
}

validate_runtime() {
  local service
  validate_port "ClickHouse HTTP" "${CLICKHOUSE_HOST}" "${CLICKHOUSE_HTTP_PORT}"
  if [[ "${DEPLOY_MODE}" == "full" ]]; then
    validate_port "ZooKeeper" 127.0.0.1 2181
  fi
  for service in "${DEPLOY_SERVICES[@]}"; do
    validate_service_port "${service}"
  done
}

deploy_full_stack() {
  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    compose --profile embedded-clickhouse pull clickhouse zookeeper "${DEPLOY_SERVICES[@]}"
    compose --profile embedded-clickhouse up -d clickhouse zookeeper
  else
    compose pull zookeeper "${DEPLOY_SERVICES[@]}"
    compose up -d zookeeper
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
    compose --profile embedded-clickhouse up -d "${DEPLOY_SERVICES[@]}"
  else
    compose up -d "${DEPLOY_SERVICES[@]}"
  fi

  if ! validate_runtime; then
    echo "Validation failed. Running rollback..." >&2
    "${ROOT_DIR}/rollback.sh"
    exit 1
  fi
}

deploy_selected_services() {
  echo "Selected-service deployment: ${DEPLOY_SERVICES[*]}"
  echo "Dependencies will not be started; ClickHouse and ZooKeeper must already be reachable."

  compose pull "${DEPLOY_SERVICES[@]}"

  if ! wait_for_clickhouse_ready; then
    echo "Configured ClickHouse is not reachable. Selected services were not started." >&2
    exit 1
  fi

  if ! wait_for_clickhouse_schema; then
    echo "Configured ClickHouse schema is not ready. Selected services were not started." >&2
    exit 1
  fi

  compose up -d --no-deps "${DEPLOY_SERVICES[@]}"

  if ! validate_runtime; then
    echo "Selected-service validation failed. Inspect the selected containers before retrying." >&2
    compose ps "${DEPLOY_SERVICES[@]}" >&2 || true
    exit 1
  fi
}

main() {
  parse_args "$@"
  check_cmd docker
  check_cmd curl
  docker compose version >/dev/null
  load_env
  check_system_requirements
  validate_ghcr_login
  validate_control_prod
  check_file "${COMPOSE_FILE}"
  prepare_runtime_dirs

  backup_control
  record_status
  sync_control
  generate_compose_overrides
  stop_legacy_services

  if [[ "${DEPLOY_MODE}" == "full" ]]; then
    deploy_full_stack
  else
    deploy_selected_services
  fi

  echo "Deployment completed successfully."
}

main "$@"
