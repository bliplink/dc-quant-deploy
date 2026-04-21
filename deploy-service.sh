#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
BACKUP_ROOT="${ROOT_DIR}/backups/service-cutover"

DRY_RUN=false
SERVICE=""

usage() {
  cat <<'USAGE'
Usage:
  ./deploy-service.sh <service> [--dry-run]

Supported services:
  gateway
  mdsvr
  apssvr
  quantsvr
  indsvr
  batchsvr
  simsvr

This script performs a single-service cutover:
  1. record baseline
  2. pull only the target service image
  3. stop only the legacy target service
  4. start only the target container with docker compose up -d --no-deps
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -n "${SERVICE}" ]]; then
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 1
      fi
      SERVICE="$1"
      shift
      ;;
  esac
done

if [[ -z "${SERVICE}" ]]; then
  usage >&2
  exit 1
fi

case "${SERVICE}" in
  gateway)
    LEGACY_SERVICE="GW"
    CONTAINER_NAME="dc-gateway"
    SERVICE_PORT="3000"
    LOG_FILE="GW.log"
    IMAGE_VAR="GW_TAG"
    ;;
  mdsvr)
    LEGACY_SERVICE="MDSvr"
    CONTAINER_NAME="dc-mdsvr"
    SERVICE_PORT="30028"
    LOG_FILE="MDSvr.log"
    IMAGE_VAR="MDSVR_TAG"
    ;;
  apssvr)
    LEGACY_SERVICE="APSSvr"
    CONTAINER_NAME="dc-apssvr"
    SERVICE_PORT="30035"
    LOG_FILE="APSSvr.log"
    IMAGE_VAR="APSSVR_TAG"
    ;;
  quantsvr)
    LEGACY_SERVICE="QuantSvr"
    CONTAINER_NAME="dc-quantsvr"
    SERVICE_PORT="30042"
    LOG_FILE="QuantSvr.log"
    IMAGE_VAR="QUANTSVR_TAG"
    ;;
  indsvr)
    LEGACY_SERVICE="INDSvr"
    CONTAINER_NAME="dc-indsvr"
    SERVICE_PORT="30044"
    LOG_FILE="INDSvr.log"
    IMAGE_VAR="INDSVR_TAG"
    ;;
  batchsvr)
    LEGACY_SERVICE="BatchSvr"
    CONTAINER_NAME="dc-batchsvr"
    SERVICE_PORT="30046"
    LOG_FILE="BatchSvr.log"
    IMAGE_VAR="BATCHSVR_TAG"
    ;;
  simsvr)
    LEGACY_SERVICE="SIMSvr"
    CONTAINER_NAME="dc-simsvr"
    SERVICE_PORT="30045"
    LOG_FILE="SIMSvr.log"
    IMAGE_VAR="SIMSVR_TAG"
    ;;
  *)
    echo "Unsupported service: ${SERVICE}" >&2
    usage >&2
    exit 1
    ;;
esac

run() {
  echo "+ $*"
  if [[ "${DRY_RUN}" != "true" ]]; then
    "$@"
  fi
}

run_shell() {
  echo "+ $*"
  if [[ "${DRY_RUN}" != "true" ]]; then
    bash -lc "$*"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_file() {
  [[ -f "$1" ]] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

load_env() {
  require_file "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
  : "${RUNTIME_UID:?RUNTIME_UID is required}"
  : "${RUNTIME_GID:?RUNTIME_GID is required}"
  SERVICE_HOST="${SERVICE_HOST:-127.0.0.1}"
  : "${CLICKHOUSE_MODE:?CLICKHOUSE_MODE is required}"
  : "${CLICKHOUSE_DB_NAME:?CLICKHOUSE_DB_NAME is required}"
  : "${CLICKHOUSE_HOST:?CLICKHOUSE_HOST is required}"
  : "${CLICKHOUSE_HTTP_PORT:?CLICKHOUSE_HTTP_PORT is required}"
  : "${CLICKHOUSE_USERNAME:?CLICKHOUSE_USERNAME is required}"
  : "${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD is required}"

  if [[ -z "${!IMAGE_VAR:-}" ]]; then
    echo "${IMAGE_VAR} is required" >&2
    exit 1
  fi

  if [[ "${CLICKHOUSE_MODE}" != "external" ]]; then
    echo "Single-service production cutover requires CLICKHOUSE_MODE=external." >&2
    exit 1
  fi
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

clickhouse_query() {
  local query="$1"

  curl -fsS --get "http://${CLICKHOUSE_HOST}:${CLICKHOUSE_HTTP_PORT}/" \
    --data-urlencode "database=${CLICKHOUSE_DB_NAME}" \
    --data-urlencode "user=${CLICKHOUSE_USERNAME}" \
    --data-urlencode "password=${CLICKHOUSE_PASSWORD}" \
    --data-urlencode "query=${query}"
}

is_port_open() {
  local host="$1"
  local port="$2"
  bash -c "exec 3<>/dev/tcp/${host}/${port}" >/dev/null 2>&1
}

wait_for_port_closed() {
  local host="$1"
  local port="$2"
  local retries="${3:-30}"
  local delay="${4:-2}"

  for _ in $(seq 1 "${retries}"); do
    if ! is_port_open "${host}" "${port}"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "Port is still open: ${host}:${port}" >&2
  return 1
}

wait_for_port_open() {
  local host="$1"
  local port="$2"
  local retries="${3:-45}"
  local delay="${4:-2}"

  for _ in $(seq 1 "${retries}"); do
    if is_port_open "${host}" "${port}"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "Port did not open: ${host}:${port}" >&2
  return 1
}

record_baseline() {
  local timestamp snapshot_dir
  timestamp="$(date '+%Y%m%d_%H%M%S')"
  snapshot_dir="${BACKUP_ROOT}/${SERVICE}_${timestamp}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "Dry run: baseline would be saved to ${snapshot_dir}"
    return 0
  fi

  mkdir -p "${snapshot_dir}"

  ps -ef > "${snapshot_dir}/ps_before.txt"
  ps -ef | grep -E 'BatchSvr|SIMSvr|INDSvr|APSSvr|MDSvr|QuantSvr|GW|Registry' | grep -v grep > "${snapshot_dir}/dc_processes_before.txt" || true
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' > "${snapshot_dir}/docker_ps_before.txt" 2>/dev/null || true
  tail -n 200 "${DEPLOY_ROOT}/log/${LOG_FILE}" > "${snapshot_dir}/${LOG_FILE}.before.tail" 2>/dev/null || true

  echo "Baseline saved to ${snapshot_dir}"
}

validate_clickhouse_external() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "Dry run: ClickHouse external connectivity and schema check skipped."
    return 0
  fi

  require_command curl

  echo "Checking external ClickHouse at ${CLICKHOUSE_HOST}:${CLICKHOUSE_HTTP_PORT}/${CLICKHOUSE_DB_NAME}..."
  clickhouse_query "SELECT 1" >/dev/null

  case "${SERVICE}" in
    batchsvr)
      local signal_count report_count
      signal_count="$(clickhouse_query "SELECT count() FROM system.tables WHERE database='${CLICKHOUSE_DB_NAME}' AND name='signal'")"
      report_count="$(clickhouse_query "SELECT count() FROM system.tables WHERE database='${CLICKHOUSE_DB_NAME}' AND name LIKE 'strategy_system_daily_report%'")"

      if [[ "${signal_count}" -lt 1 ]]; then
        echo "Missing required ClickHouse table: ${CLICKHOUSE_DB_NAME}.signal" >&2
        exit 1
      fi

      if [[ "${report_count}" -lt 1 ]]; then
        echo "Missing required ClickHouse report tables: ${CLICKHOUSE_DB_NAME}.strategy_system_daily_report*" >&2
        exit 1
      fi

      echo "External ClickHouse connectivity and BatchSvr schema check passed."
      ;;
    simsvr)
      local backtest_table_count
      backtest_table_count="$(clickhouse_query "SELECT count() FROM system.tables WHERE database='${CLICKHOUSE_DB_NAME}' AND name IN ('strategy_backtest_task','backtest_result')")"

      if [[ "${backtest_table_count}" -lt 2 ]]; then
        echo "Missing required ClickHouse tables for SIMSvr: ${CLICKHOUSE_DB_NAME}.strategy_backtest_task and/or ${CLICKHOUSE_DB_NAME}.backtest_result" >&2
        exit 1
      fi

      echo "External ClickHouse connectivity and SIMSvr schema check passed."
      ;;
    indsvr)
      local generation_table_count
      generation_table_count="$(clickhouse_query "SELECT count() FROM system.tables WHERE database='${CLICKHOUSE_DB_NAME}' AND name IN ('strategy_generation_task','strategy_candidate')")"

      if [[ "${generation_table_count}" -lt 2 ]]; then
        echo "Missing required ClickHouse tables for INDSvr: ${CLICKHOUSE_DB_NAME}.strategy_generation_task and/or ${CLICKHOUSE_DB_NAME}.strategy_candidate" >&2
        exit 1
      fi

      echo "External ClickHouse connectivity and INDSvr schema check passed."
      ;;
    quantsvr)
      local runtime_table_count
      runtime_table_count="$(clickhouse_query "SELECT count() FROM system.tables WHERE database='${CLICKHOUSE_DB_NAME}' AND name IN ('signal','quant_order','strategy_live_registry')")"

      if [[ "${runtime_table_count}" -lt 3 ]]; then
        echo "Missing required ClickHouse tables for QuantSvr: ${CLICKHOUSE_DB_NAME}.signal, ${CLICKHOUSE_DB_NAME}.quant_order and/or ${CLICKHOUSE_DB_NAME}.strategy_live_registry" >&2
        exit 1
      fi

      echo "External ClickHouse connectivity and QuantSvr schema check passed."
      ;;
    gateway|mdsvr|apssvr)
      echo "External ClickHouse connectivity check passed for ${LEGACY_SERVICE}."
      ;;
  esac
}

stop_legacy_service() {
  if [[ "${DRY_RUN}" != "true" && ! -x "${DEPLOY_ROOT}/scripts/stop" ]]; then
    echo "Missing legacy stop script: ${DEPLOY_ROOT}/scripts/stop" >&2
    exit 1
  fi

  run_shell "cd '${DEPLOY_ROOT}/scripts' && ./stop '${LEGACY_SERVICE}' || true"

  if [[ "${DRY_RUN}" != "true" ]]; then
    wait_for_port_closed "${SERVICE_HOST}" "${SERVICE_PORT}"
  fi
}

pull_service_image() {
  run compose pull "${SERVICE}"
}

start_container_service() {
  run compose up -d --no-deps "${SERVICE}"
}

validate_container_service() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "Dry run: validation skipped."
    return 0
  fi

  local running
  running="$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  if [[ "${running}" != "true" ]]; then
    echo "Container is not running: ${CONTAINER_NAME}" >&2
    docker ps -a --filter "name=${CONTAINER_NAME}" >&2 || true
    exit 1
  fi

  wait_for_port_open "${SERVICE_HOST}" "${SERVICE_PORT}"

  docker logs "${CONTAINER_NAME}" --tail 200

  if docker logs "${CONTAINER_NAME}" --tail 200 2>&1 | grep -Ei 'permission denied|address already in use' >/dev/null; then
    echo "Container log contains startup-blocking error." >&2
    exit 1
  fi

  if docker logs "${CONTAINER_NAME}" --tail 200 2>&1 | grep -Ei '(^|[[:space:]])ERROR([[:space:]]|$)|Exception' >/dev/null; then
    echo "Warning: container log contains ERROR/Exception. Review before considering the cutover stable." >&2
  fi

  tail -n 80 "${DEPLOY_ROOT}/log/${LOG_FILE}" || true
}

main() {
  if [[ "${DRY_RUN}" != "true" ]]; then
    require_command docker
    docker compose version >/dev/null
  fi
  load_env
  require_file "${COMPOSE_FILE}"

  echo "Single-service cutover target: ${SERVICE}"
  echo "Legacy service: ${LEGACY_SERVICE}"
  echo "Container: ${CONTAINER_NAME}"
  echo "Port: ${SERVICE_PORT}"
  echo "Port check host: ${SERVICE_HOST}"
  echo "Image tag variable: ${IMAGE_VAR}=${!IMAGE_VAR}"
  echo "Docker command will use --no-deps."

  record_baseline
  validate_clickhouse_external
  pull_service_image
  stop_legacy_service
  start_container_service
  validate_container_service

  echo "Single-service cutover completed for ${SERVICE}."
}

main "$@"
