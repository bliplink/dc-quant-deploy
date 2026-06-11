#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${ROOT_DIR}/generate-compose-overrides.sh"

DRY_RUN=false
INCLUDE_INFRA=false

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

INFRA_SERVICES=(
  zookeeper
  clickhouse
)

REQUESTED_SERVICES=()

usage() {
  cat <<'USAGE'
Usage:
  ./pull-images.sh [--include-infra] [--dry-run] [service...]

Examples:
  ./pull-images.sh
  ./pull-images.sh indsvr quantsvr batchsvr
  ./pull-images.sh --include-infra
  ./pull-images.sh --include-infra gateway indsvr

Behavior:
  - Without service arguments, pull all app services:
      gateway loginsvr mdsvr apssvr quantsvr indsvr simsvr batchsvr web
  - With --include-infra, also pull:
      zookeeper clickhouse
  - This script only pulls images. It does not restart any service.
USAGE
}

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

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -f "${OVERRIDE_FILE}" "$@"
}

load_env() {
  require_file "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
  : "${CLICKHOUSE_MODE:?CLICKHOUSE_MODE is required}"
}

generate_compose_overrides() {
  require_file "${GENERATE_OVERRIDES_SCRIPT}"
  run bash "${GENERATE_OVERRIDES_SCRIPT}" "${ENV_FILE}" "${OVERRIDE_FILE}"
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

append_unique_service() {
  local needle="$1"
  if ! contains_service "${needle}" "${REQUESTED_SERVICES[@]:-}"; then
    REQUESTED_SERVICES+=("${needle}")
  fi
}

normalize_service() {
  local value="$1"
  case "${value}" in
    GW|gw)
      echo "gateway"
      ;;
    gateway|loginsvr|mdsvr|apssvr|quantsvr|indsvr|simsvr|batchsvr|web|zookeeper|clickhouse)
      echo "${value}"
      ;;
    *)
      echo ""
      ;;
  esac
}

resolve_services() {
  local raw normalized

  if [[ "${#REQUESTED_SERVICES[@]}" -eq 0 ]]; then
    REQUESTED_SERVICES=("${APP_SERVICES[@]}")
  else
    local resolved=()
    for raw in "${REQUESTED_SERVICES[@]}"; do
      normalized="$(normalize_service "${raw}")"
      if [[ -z "${normalized}" ]]; then
        echo "Unsupported service: ${raw}" >&2
        usage >&2
        exit 1
      fi
      if ! contains_service "${normalized}" "${resolved[@]:-}"; then
        resolved+=("${normalized}")
      fi
    done
    REQUESTED_SERVICES=("${resolved[@]}")
  fi

  if [[ "${INCLUDE_INFRA}" == "true" ]]; then
    if [[ "${CLICKHOUSE_MODE}" == "embedded" ]]; then
      append_unique_service "clickhouse"
    fi
    append_unique_service "zookeeper"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --include-infra)
      INCLUDE_INFRA=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      REQUESTED_SERVICES+=("$1")
      shift
      ;;
  esac
done

main() {
  if [[ "${DRY_RUN}" != "true" ]]; then
    require_command docker
    docker compose version >/dev/null
  fi

  require_file "${COMPOSE_FILE}"
  load_env
  generate_compose_overrides
  resolve_services

  echo "Pull target services: ${REQUESTED_SERVICES[*]}"
  echo "Include infra: ${INCLUDE_INFRA}"
  echo "ClickHouse mode: ${CLICKHOUSE_MODE}"

  run compose pull "${REQUESTED_SERVICES[@]}"

  echo "Image pull completed."
  echo "Next step example:"
  echo "  ./restart-service.sh indsvr"
}

main "$@"
