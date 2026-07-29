#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
ENV_DEFAULT="${ROOT_DIR}/.env.example"
ENV_STANDALONE_EXAMPLE="${ROOT_DIR}/.env.standalone.example"
ENV_EXTERNAL_EXAMPLE="${ROOT_DIR}/.env.external-clickhouse.example"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${ROOT_DIR}/generate-compose-overrides.sh"
CONTROL_SRC="${ROOT_DIR}/control.prod"
CONTROL_EXAMPLE_DIR="${ROOT_DIR}/control.prod.example"
PREPARE_HOST_SCRIPT="${ROOT_DIR}/prepare-host.sh"
LAST_BACKUP_FILE="${ROOT_DIR}/.last_backup"
BACKUP_ROOT="${ROOT_DIR}/backups"

SERVICE_NAMES=(
  "tpc/Registry"
  "dc/GW/GW"
  "dc/LoginSvr/LoginSvr"
  "dc/MDSvr/MDSvr"
  "dc/APSSvr/APSSvr"
  "dc/QuantSvr/QuantSvr"
  "dc/INDSvr/INDSvr"
  "dc/SIMSvr/SIMSvr"
  "dc/BatchSvr/BatchSvr"
)
APP_SERVICES=(
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
START_LOCAL_DEPS=false
LICENSE_URL_OVERRIDE=""
CLICKHOUSE_INIT_SCRIPT="${ROOT_DIR}/clickhouse/apply-init.sh"

usage() {
  cat <<'USAGE'
Usage:
  ./deploy.sh
  ./deploy.sh --services SERVICE[,SERVICE...]
  ./deploy.sh --services SERVICE[,SERVICE...] --with-deps
  ./deploy.sh --services SERVICE[,SERVICE...] --license-url HTTPS_URL

Without --services, deploy the complete stack.

The script bootstraps Docker when missing, creates .env.prod and control.prod
defaults when missing, prepares runtime mount directories, and validates the
result.

With --services, deploy only the selected application containers. By default,
local dependencies are not started; configure reachable external ClickHouse
and ZooKeeper addresses before deployment.

With --with-deps, start embedded ClickHouse and start ZooKeeper only when a
selected service has RegisterEnable=1. Other application services are not
started.

With --license-url, download dc.dat from the specified HTTPS URL when the
current control.prod/dc.dat is missing or still contains placeholder content.

Supported service names:
  gateway, loginsvr, mdsvr, apssvr, quantsvr, indsvr, simsvr, batchsvr, web

Example:
  ./deploy.sh --services apssvr --license-url https://example.com/dc.dat
  ./deploy.sh --services loginsvr --with-deps
USAGE
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -f "${OVERRIDE_FILE}" "$@"
}

compose_pull_with_retry() {
  local attempt
  local attempts="${IMAGE_PULL_ATTEMPTS:-5}"
  local delay_seconds="${IMAGE_PULL_RETRY_DELAY_SECONDS:-10}"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if compose "$@"; then
      return 0
    fi
    if [[ "${attempt}" -lt "${attempts}" ]]; then
      echo "Image pull failed (attempt ${attempt}/${attempts}); retrying in ${delay_seconds}s." >&2
      sleep "${delay_seconds}"
    fi
  done

  echo "Image pull failed after ${attempts} attempts." >&2
  return 1
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

service_requires_clickhouse() {
  case "$1" in
    apssvr|mdsvr)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

selected_services_require_clickhouse() {
  local service
  for service in "${DEPLOY_SERVICES[@]}"; do
    if service_requires_clickhouse "${service}"; then
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
      --with-deps)
        START_LOCAL_DEPS=true
        ;;
      --license-url)
        shift
        [[ "$#" -gt 0 ]] || {
          echo "--license-url requires an HTTPS URL." >&2
          exit 1
        }
        [[ "$1" == https://* ]] || {
          echo "--license-url only accepts HTTPS URLs." >&2
          exit 1
        }
        LICENSE_URL_OVERRIDE="$1"
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
    if [[ "${START_LOCAL_DEPS}" == "true" ]]; then
      echo "--with-deps is only valid with --services." >&2
      exit 1
    fi
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

copy_if_missing() {
  local src="$1"
  local dst="$2"
  if [ ! -e "${dst}" ]; then
    mkdir -p "$(dirname "${dst}")"
    cp -a "${src}" "${dst}"
    echo "Created ${dst} from deployment defaults."
  fi
}

prepare_deploy_defaults() {
  local env_example="${ENV_DEFAULT}"

  if [[ "${DEPLOY_MODE}" == "selected" ]]; then
    if [[ "${START_LOCAL_DEPS}" == "true" ]]; then
      env_example="${ENV_STANDALONE_EXAMPLE}"
    else
      env_example="${ENV_EXTERNAL_EXAMPLE}"
    fi
  fi

  check_file "${env_example}"
  check_dir "${CONTROL_EXAMPLE_DIR}"
  copy_if_missing "${env_example}" "${ENV_FILE}"

  mkdir -p "${CONTROL_SRC}"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/ATSConfig.ini" "${CONTROL_SRC}/ATSConfig.ini"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/DBPoolConfig.ini" "${CONTROL_SRC}/DBPoolConfig.ini"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/jaas.ini" "${CONTROL_SRC}/jaas.ini"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/dc.dat" "${CONTROL_SRC}/dc.dat"
  if [ -d "${CONTROL_EXAMPLE_DIR}/overrides" ] && [ ! -e "${CONTROL_SRC}/overrides" ]; then
    cp -a "${CONTROL_EXAMPLE_DIR}/overrides" "${CONTROL_SRC}/overrides"
    echo "Created ${CONTROL_SRC}/overrides from deployment defaults."
  fi
}

ensure_container_runtime() {
  if command -v docker >/dev/null 2>&1 &&
     docker compose version >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]] && [[ -f "${PREPARE_HOST_SCRIPT}" ]]; then
      "${PREPARE_HOST_SCRIPT}"
    fi
    return 0
  fi

  check_file "${PREPARE_HOST_SCRIPT}"
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Docker is missing. Re-run this deployment command as root so the host can be prepared automatically." >&2
    exit 1
  fi

  echo "Docker runtime is missing; preparing the host automatically."
  "${PREPARE_HOST_SCRIPT}"
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
  DC_LICENSE_URL="${LICENSE_URL_OVERRIDE:-${DC_LICENSE_URL:-}}"
}

check_system_requirements() {
  local min_mem_mb min_disk_gb mem_mb disk_mb disk_gb
  local docker_driver docker_root docker_disk_mb docker_disk_gb min_docker_disk_gb
  if [[ "${DEPLOY_MODE}" == "selected" ]]; then
    min_mem_mb="${MIN_SELECTED_MEMORY_MB:-1024}"
    min_disk_gb="${MIN_SELECTED_DISK_GB:-5}"
  else
    min_mem_mb="${MIN_MEMORY_MB:-8192}"
    min_disk_gb="${MIN_DISK_GB:-20}"
  fi

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

  docker_driver="$(docker info --format '{{.Driver}}')"
  docker_root="$(docker info --format '{{.DockerRootDir}}')"
  docker_disk_mb="$(df -Pm "${docker_root}" | awk 'NR==2 {print $4}')"
  docker_disk_gb="$((docker_disk_mb / 1024))"
  min_docker_disk_gb="${min_disk_gb}"
  if [[ "${docker_driver}" == "vfs" ]]; then
    if [[ "${DEPLOY_MODE}" == "selected" ]]; then
      min_docker_disk_gb="${MIN_SELECTED_VFS_DOCKER_DISK_GB:-10}"
    else
      min_docker_disk_gb="${MIN_VFS_DOCKER_DISK_GB:-120}"
    fi
  fi

  if [ "${docker_disk_gb}" -lt "${min_docker_disk_gb}" ]; then
    echo "Machine check failed: Docker uses ${docker_driver} with ${docker_disk_gb} GB free at ${docker_root}; required >= ${min_docker_disk_gb} GB." >&2
    if [[ "${docker_driver}" == "vfs" ]]; then
      echo "Move Docker's data-root to a larger filesystem before deployment (for example DOCKER_DATA_ROOT=/opt/sumscope/docker-data)." >&2
    fi
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
  ensure_license_file
  check_file "${CONTROL_SRC}/dc.dat"
}

license_is_placeholder() {
  local license_file="$1"

  [ -s "${license_file}" ] || return 0
  LC_ALL=C grep -aqE \
    '^(dc\.dat|Copy your valid dc\.dat license content here before deployment\.)[[:space:]]*$' \
    "${license_file}"
}

ensure_license_file() {
  local license_file="${CONTROL_SRC}/dc.dat"
  local temporary_file

  if [ -f "${license_file}" ] && ! license_is_placeholder "${license_file}"; then
    return 0
  fi

  if [[ -z "${DC_LICENSE_URL:-}" ]]; then
    echo "A valid control.prod/dc.dat license is required before deployment." >&2
    echo "Provide it with --license-url HTTPS_URL or DC_LICENSE_URL in .env.prod." >&2
    exit 1
  fi

  temporary_file="$(mktemp "${CONTROL_SRC}/.dc.dat.XXXXXX")"
  if ! curl -fsSL "${DC_LICENSE_URL}" -o "${temporary_file}"; then
    rm -f "${temporary_file}"
    echo "Failed to download dc.dat from the configured license URL." >&2
    exit 1
  fi

  if license_is_placeholder "${temporary_file}"; then
    rm -f "${temporary_file}"
    echo "The downloaded dc.dat is empty or contains placeholder content." >&2
    exit 1
  fi

  chmod 600 "${temporary_file}"
  mv -f "${temporary_file}" "${license_file}"
  echo "Downloaded a non-placeholder dc.dat license into control.prod."
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
  local source_item target_item staged_item base_name

  mkdir -p "${DEPLOY_ROOT}/control"
  mkdir -p "${DEPLOY_ROOT}/control/overrides"

  while IFS= read -r -d '' source_item; do
    base_name="$(basename "${source_item}")"
    target_item="${DEPLOY_ROOT}/control/${base_name}"
    staged_item="${DEPLOY_ROOT}/control/.${base_name}.deploy-new.$$"
    rm -rf "${staged_item}"
    cp -a "${source_item}" "${staged_item}"

    if { [ -d "${source_item}" ] && [ ! -L "${source_item}" ]; } ||
       { [ -d "${target_item}" ] && [ ! -L "${target_item}" ]; }; then
      rm -rf "${target_item}"
      mv "${staged_item}" "${target_item}"
    else
      mv -f "${staged_item}" "${target_item}"
    fi
  done < <(
    find "${CONTROL_SRC}" -mindepth 1 -maxdepth 1 ! -name overrides -print0
  )

  while IFS= read -r -d '' target_item; do
    base_name="$(basename "${target_item}")"
    if [ ! -e "${CONTROL_SRC}/${base_name}" ] &&
       [ ! -L "${CONTROL_SRC}/${base_name}" ]; then
      rm -rf "${target_item}"
    fi
  done < <(
    find "${DEPLOY_ROOT}/control" -mindepth 1 -maxdepth 1 \
      ! -name overrides ! -name '.*.deploy-new.*' -print0
  )

  if [ -d "${CONTROL_SRC}/overrides" ]; then
    cp -an "${CONTROL_SRC}/overrides/." "${DEPLOY_ROOT}/control/overrides/"
  fi

  if [ -f "${DEPLOY_ROOT}/control/dc.dat" ]; then
    # Keep the source license root-only while allowing the runtime group to read its copy.
    chown "root:${RUNTIME_GID}" "${DEPLOY_ROOT}/control/dc.dat"
    chmod 0640 "${DEPLOY_ROOT}/control/dc.dat"
  fi
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
        loginsvr) legacy_services+=("dc/LoginSvr/LoginSvr") ;;
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

port_is_open() {
  local host="$1"
  local port="$2"
  bash -c "exec 3<>/dev/tcp/${host}/${port}" >/dev/null 2>&1
}

container_is_running() {
  local container_name="$1"
  [[ "$(docker inspect --format '{{.State.Status}}' "${container_name}" 2>/dev/null || true)" == "running" ]]
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
    loginsvr) validate_port "LoginSvr" "${SERVICE_HOST:-127.0.0.1}" 20034 ;;
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
  local failed=0
  if [[ "${DEPLOY_MODE}" == "full" ]] || selected_services_require_clickhouse; then
    validate_port "ClickHouse HTTP" "${CLICKHOUSE_HOST}" "${CLICKHOUSE_HTTP_PORT}" || failed=1
  fi
  if [[ "${DEPLOY_MODE}" == "full" ]]; then
    validate_port "ZooKeeper" 127.0.0.1 2181 || failed=1
  fi
  for service in "${DEPLOY_SERVICES[@]}"; do
    validate_service_port "${service}" || failed=1
  done
  return "${failed}"
}

deploy_full_stack() {
  local use_existing_zookeeper=false
  if port_is_open 127.0.0.1 2181 && ! container_is_running dc-zookeeper; then
    use_existing_zookeeper=true
    echo "Reusing the existing ZooKeeper listener on 127.0.0.1:2181."
    docker rm -f dc-zookeeper >/dev/null 2>&1 || true
  fi

  if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
    if [[ "${use_existing_zookeeper}" == "true" ]]; then
      compose_pull_with_retry --profile embedded-clickhouse pull clickhouse "${DEPLOY_SERVICES[@]}"
      compose --profile embedded-clickhouse up -d clickhouse
    else
      compose_pull_with_retry --profile embedded-clickhouse pull clickhouse zookeeper "${DEPLOY_SERVICES[@]}"
      compose --profile embedded-clickhouse up -d clickhouse zookeeper
    fi
  else
    if [[ "${use_existing_zookeeper}" == "true" ]]; then
      compose_pull_with_retry pull "${DEPLOY_SERVICES[@]}"
    else
      compose_pull_with_retry pull zookeeper "${DEPLOY_SERVICES[@]}"
      compose up -d zookeeper
    fi
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

  if [[ "${use_existing_zookeeper}" == "true" ]]; then
    if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
      compose --profile embedded-clickhouse up -d --no-deps "${DEPLOY_SERVICES[@]}"
    else
      compose up -d --no-deps "${DEPLOY_SERVICES[@]}"
    fi
  elif [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
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
  local requires_clickhouse=false
  if selected_services_require_clickhouse; then
    requires_clickhouse=true
  fi

  echo "Selected-service deployment: ${DEPLOY_SERVICES[*]}"
  if [[ "${START_LOCAL_DEPS}" == "true" ]]; then
    local -a infrastructure=()
    local -a pull_services=()
    local service config_name register_enable

    if [[ "${requires_clickhouse}" == "true" &&
          "${CLICKHOUSE_MODE}" != "embedded" ]]; then
      echo "--with-deps requires CLICKHOUSE_MODE=embedded in ${ENV_FILE}." >&2
      exit 1
    fi

    if [[ "${requires_clickhouse}" == "true" ]]; then
      infrastructure+=(clickhouse)
      pull_services+=(clickhouse)
    fi

    for service in "${DEPLOY_SERVICES[@]}"; do
      case "${service}" in
        gateway) config_name="GW" ;;
        loginsvr) config_name="LoginSvr" ;;
        mdsvr) config_name="MDSvr" ;;
        apssvr) config_name="APSSvr" ;;
        quantsvr) config_name="QuantSvr" ;;
        indsvr) config_name="INDSvr" ;;
        simsvr) config_name="SIMSvr" ;;
        batchsvr) config_name="BatchSvr" ;;
        *) config_name="" ;;
      esac

      if [[ -n "${config_name}" ]]; then
        register_enable="$(
          sed -n "s/^SERVER\\.${config_name}\\.RegisterEnable=//p" \
            "${CONTROL_SRC}/ATSConfig.ini" | tail -n 1
        )"
        if [[ "${register_enable}" == "1" ]] &&
           ! contains_service "zookeeper" "${infrastructure[@]}"; then
          infrastructure+=(zookeeper)
          pull_services+=(zookeeper)
        fi
      fi
    done
    pull_services+=("${DEPLOY_SERVICES[@]}")

    if [[ "${#infrastructure[@]}" -gt 0 ]]; then
      echo "Starting local infrastructure: ${infrastructure[*]}"
    else
      echo "No local infrastructure is required by the selected services."
    fi
    compose_pull_with_retry --profile embedded-clickhouse pull "${pull_services[@]}"
    if [[ "${#infrastructure[@]}" -gt 0 ]]; then
      compose --profile embedded-clickhouse up -d "${infrastructure[@]}"
    fi

    if [[ "${requires_clickhouse}" == "true" ]]; then
      if ! wait_for_clickhouse_ready; then
        echo "Embedded ClickHouse did not become ready. Selected services were not started." >&2
        exit 1
      fi

      if ! wait_for_clickhouse_schema 2 1; then
        if ! apply_clickhouse_init; then
          echo "Embedded ClickHouse initialization failed. Selected services were not started." >&2
          exit 1
        fi
      fi

      if ! wait_for_clickhouse_schema; then
        echo "Embedded ClickHouse schema is not ready. Selected services were not started." >&2
        exit 1
      fi
    fi

    compose --profile embedded-clickhouse up -d --force-recreate --no-deps \
      "${DEPLOY_SERVICES[@]}"
  else
    echo "Local dependencies will not be started."
    compose_pull_with_retry pull "${DEPLOY_SERVICES[@]}"

    if [[ "${requires_clickhouse}" == "true" ]]; then
      if ! wait_for_clickhouse_ready; then
        echo "Configured ClickHouse is not reachable. Selected services were not started." >&2
        exit 1
      fi

      if ! wait_for_clickhouse_schema; then
        echo "Configured ClickHouse schema is not ready. Selected services were not started." >&2
        exit 1
      fi
    else
      echo "The selected services do not require ClickHouse; database checks were skipped."
    fi

    compose up -d --force-recreate --no-deps "${DEPLOY_SERVICES[@]}"
  fi

  if ! validate_runtime; then
    echo "Selected-service validation failed. Inspect the selected containers before retrying." >&2
    compose ps "${DEPLOY_SERVICES[@]}" >&2 || true
    exit 1
  fi
}

main() {
  parse_args "$@"
  prepare_deploy_defaults
  ensure_container_runtime
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
