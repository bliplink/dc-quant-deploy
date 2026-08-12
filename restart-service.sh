#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${ROOT_DIR}/generate-compose-overrides.sh"
VALIDATE_ENV_SCRIPT="${ROOT_DIR}/validate-env.sh"

DRY_RUN=false
SERVICE=""

usage() {
  cat <<'USAGE'
Usage:
  ./restart-service.sh <service> [--dry-run]

Supported services:
  GW
  loginsvr
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
    SERVICE_PORT=""
    LOG_FILE="GW.log"
    ;;
  loginsvr)
    CONTAINER_NAME="dc-loginsvr"
    SERVICE_PORT="20034"
    LOG_FILE="LoginSvr.log"
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
    SERVICE_PORT=""
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

require_http_command() {
  if command -v curl >/dev/null 2>&1; then
    echo "curl"
    return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    echo "wget"
    return 0
  fi
  echo "Missing required HTTP command: curl or wget" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

load_env() {
  require_file "${ENV_FILE}"
  require_file "${VALIDATE_ENV_SCRIPT}"
  bash "${VALIDATE_ENV_SCRIPT}" "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
  SERVICE_HOST="${SERVICE_HOST:-127.0.0.1}"
  case "${COMPOSE_SERVICE}" in
    gateway) SERVICE_PORT="${GATEWAY_PORT:-3002}" ;;
    web) SERVICE_PORT="${WEB_LISTEN_PORT:-80}" ;;
  esac
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

port_owned_by_container() {
  local container_name="$1"
  local port="$2"
  docker exec --user 0 "${container_name}" sh -c '
    port_hex=$(printf "%04X" "$1")
    inodes=$(awk -v suffix=":${port_hex}" '\''$2 ~ suffix "$" && $4 == "0A" { print $10 }'\'' \
      /proc/net/tcp /proc/net/tcp6 2>/dev/null)
    for inode in ${inodes}; do
      for fd in /proc/[0-9]*/fd/*; do
        [ "$(readlink "${fd}" 2>/dev/null)" = "socket:[${inode}]" ] && exit 0
      done
    done
    exit 1
  ' sh "${port}" >/dev/null 2>&1
}

wait_for_owned_port() {
  local container_name="$1"
  local port="$2"
  local retries="${3:-45}"
  local delay="${4:-2}"

  for _ in $(seq 1 "${retries}"); do
    if port_owned_by_container "${container_name}" "${port}"; then
      return 0
    fi
    sleep "${delay}"
  done

  echo "Container ${container_name} does not own expected port ${port}." >&2
  ss -H -lntp "sport = :${port}" >&2 || true
  return 1
}

http_fetch() {
  local http_cmd="$1"
  local url="$2"
  local output_path="$3"
  if [[ "${http_cmd}" == "curl" ]]; then
    curl -fsS --http1.1 --max-time 20 -H 'Cache-Control: no-cache' "${url}" -o "${output_path}"
    return
  fi
  wget -qO "${output_path}" --timeout=20 --header='Cache-Control: no-cache' "${url}"
}

validate_web_delivery() {
  local http_cmd verify_host base_url tmp_dir index_html assets
  http_cmd="$(require_http_command)"
  verify_host="${WEB_VERIFY_HOST:-127.0.0.1}"
  base_url="http://${verify_host}"
  tmp_dir="$(mktemp -d)"
  trap '[[ -n "${tmp_dir:-}" ]] && rm -rf "${tmp_dir}"' RETURN

  for round in 1 2 3; do
    index_html="${tmp_dir}/index_${round}.html"
    http_fetch "${http_cmd}" "${base_url}/web/" "${index_html}"
    grep -q '/web/assets/' "${index_html}" || {
      echo "web index missing asset references on round ${round}" >&2
      return 1
    }
    mapfile -t assets < <(grep -Eo '/web/assets/[^"]+' "${index_html}" | sort -u)
    if [[ "${#assets[@]}" -eq 0 ]]; then
      echo "web index did not expose any assets on round ${round}" >&2
      return 1
    fi
    for asset in "${assets[@]}"; do
      http_fetch "${http_cmd}" "${base_url}${asset}" /dev/null
    done
  done
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
  if [[ "${COMPOSE_SERVICE}" != "zookeeper" ]]; then
    wait_for_owned_port "${CONTAINER_NAME}" "${SERVICE_PORT}"
    case "${COMPOSE_SERVICE}" in
      gateway)
        wait_for_owned_port "${CONTAINER_NAME}" "${GW_TCP_PORT:-3000}"
        wait_for_owned_port "${CONTAINER_NAME}" "${GW_WEBSOCKET_PORT:-3001}"
        ;;
      loginsvr)
        wait_for_owned_port "${CONTAINER_NAME}" "${LOGINSVR_HTTP_PORT:-19990}"
        ;;
    esac
  fi

  if [[ "${COMPOSE_SERVICE}" == "web" ]]; then
    validate_web_delivery
  fi

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
