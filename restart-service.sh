#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${ROOT_DIR}/generate-compose-overrides.sh"

DRY_RUN=false
SERVICE=""

usage() {
  cat <<'USAGE'
Usage:
  ./restart-service.sh <service> [--dry-run]

Supported services:
  GW
  mdsvr
  apssvr
  quantsvr
  indsvr
  batchsvr
  simsvr
  web
  zookeeper

This script restarts exactly one containerized service with:
  docker compose up -d --no-deps --force-recreate <service>

It does not pull a new image and does not start dependency services.
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
  GW|gw)
    COMPOSE_SERVICE="gateway"
    DISPLAY_SERVICE="GW"
    ;;
  *)
    COMPOSE_SERVICE="${SERVICE}"
    DISPLAY_SERVICE="${SERVICE}"
    ;;
esac

case "${COMPOSE_SERVICE}" in
  gateway)
    CONTAINER_NAME="dc-gateway"
    SERVICE_PORT="3000"
    LOG_FILE="GW.log"
    ;;
  mdsvr)
    CONTAINER_NAME="dc-mdsvr"
    SERVICE_PORT="30028"
    LOG_FILE="MDSvr.log"
    ;;
  apssvr)
    CONTAINER_NAME="dc-apssvr"
    SERVICE_PORT="30035"
    LOG_FILE="APSSvr.log"
    ;;
  quantsvr)
    CONTAINER_NAME="dc-quantsvr"
    SERVICE_PORT="30042"
    LOG_FILE="QuantSvr.log"
    ;;
  indsvr)
    CONTAINER_NAME="dc-indsvr"
    SERVICE_PORT="30044"
    LOG_FILE="INDSvr.log"
    ;;
  batchsvr)
    CONTAINER_NAME="dc-batchsvr"
    SERVICE_PORT="30046"
    LOG_FILE="BatchSvr.log"
    ;;
  simsvr)
    CONTAINER_NAME="dc-simsvr"
    SERVICE_PORT="30045"
    LOG_FILE="SIMSvr.log"
    ;;
  web)
    CONTAINER_NAME="dc-web"
    SERVICE_PORT="80"
    LOG_FILE=""
    ;;
  zookeeper)
    CONTAINER_NAME="dc-zookeeper"
    SERVICE_PORT="2181"
    LOG_FILE=""
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
  SERVICE_HOST="${SERVICE_HOST:-127.0.0.1}"
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -f "${OVERRIDE_FILE}" "$@"
}

generate_compose_overrides() {
  require_file "${GENERATE_OVERRIDES_SCRIPT}"
  run bash "${GENERATE_OVERRIDES_SCRIPT}" "${ENV_FILE}" "${OVERRIDE_FILE}"
}

is_port_open() {
  local host="$1"
  local port="$2"
  bash -c "exec 3<>/dev/tcp/${host}/${port}" >/dev/null 2>&1
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

  docker ps --filter "name=${CONTAINER_NAME}" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  docker logs "${CONTAINER_NAME}" --tail 120 || true

  if [[ -n "${LOG_FILE}" ]]; then
    tail -n 80 "${DEPLOY_ROOT}/log/${LOG_FILE}" || true
  fi
}

main() {
  if [[ "${DRY_RUN}" != "true" ]]; then
    require_command docker
    docker compose version >/dev/null
  fi

  load_env
  require_file "${COMPOSE_FILE}"
  generate_compose_overrides

  echo "Restart target: ${DISPLAY_SERVICE}"
  echo "Container: ${CONTAINER_NAME}"
  echo "Port: ${SERVICE_PORT}"
  echo "Port check host: ${SERVICE_HOST}"
  echo "Docker command will use --no-deps --force-recreate."

  run compose up -d --no-deps --force-recreate "${COMPOSE_SERVICE}"
  validate_container_service

  echo "Restart completed for ${DISPLAY_SERVICE}."
}

main "$@"
