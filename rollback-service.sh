#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"

DRY_RUN=false
SERVICE=""

usage() {
  cat <<'USAGE'
Usage:
  ./rollback-service.sh <service> [--dry-run]

Supported services:
  batchsvr

This script rolls back one service:
  1. stop only the target container
  2. restart only the legacy target service
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
  batchsvr)
    LEGACY_SERVICE="BatchSvr"
    CONTAINER_NAME="dc-batchsvr"
    SERVICE_PORT="30046"
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
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
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

main() {
  load_env
  require_file "${COMPOSE_FILE}"

  echo "Rollback target: ${SERVICE}"
  echo "Container: ${CONTAINER_NAME}"
  echo "Legacy service: ${LEGACY_SERVICE}"
  echo "Port check host: ${SERVICE_HOST}"

  run compose stop "${SERVICE}"

  if [[ "${DRY_RUN}" != "true" && ! -x "${DEPLOY_ROOT}/scripts/start" ]]; then
    echo "Missing legacy start script: ${DEPLOY_ROOT}/scripts/start" >&2
    exit 1
  fi

  run_shell "cd '${DEPLOY_ROOT}/scripts' && ./start '${LEGACY_SERVICE}'"

  if [[ "${DRY_RUN}" != "true" ]]; then
    wait_for_port_open "${SERVICE_HOST}" "${SERVICE_PORT}"
    ps -ef | grep "${LEGACY_SERVICE}" | grep -v grep || true
  fi

  echo "Rollback completed for ${SERVICE}."
}

main "$@"
