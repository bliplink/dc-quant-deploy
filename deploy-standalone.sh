#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
DEPLOY_SCRIPT="${ROOT_DIR}/deploy.sh"

usage() {
  cat <<'USAGE'
Usage:
  ./deploy-standalone.sh

Deploy the full stack from scratch, including the embedded ClickHouse container.

This script:
  1. backs up .env.prod
  2. sets CLICKHOUSE_MODE=embedded
  3. sets CLICKHOUSE_HOST=127.0.0.1
  4. checks that ClickHouse ports are not already occupied by another process
  5. delegates to ./deploy.sh
USAGE
}

check_file() {
  [ -f "$1" ] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

set_env_value() {
  local key="$1"
  local value="$2"

  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

load_env() {
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${CLICKHOUSE_HTTP_PORT:?CLICKHOUSE_HTTP_PORT is required}"
  : "${CLICKHOUSE_NATIVE_PORT:?CLICKHOUSE_NATIVE_PORT is required}"
}

is_port_open() {
  local host="$1"
  local port="$2"
  bash -c "exec 3<>/dev/tcp/${host}/${port}" >/dev/null 2>&1
}

check_embedded_ports() {
  local clickhouse_running
  clickhouse_running="$(docker ps --filter 'name=^/dc-clickhouse$' --format '{{.Names}}' 2>/dev/null || true)"

  if [[ "${clickhouse_running}" == "dc-clickhouse" ]]; then
    return 0
  fi

  if is_port_open 127.0.0.1 "${CLICKHOUSE_HTTP_PORT}"; then
    echo "Port ${CLICKHOUSE_HTTP_PORT} is already in use, but dc-clickhouse is not running." >&2
    echo "Standalone deployment would conflict with an existing ClickHouse or another service." >&2
    echo "Use ./deploy-with-external-clickhouse.sh if you already have ClickHouse." >&2
    exit 1
  fi

  if is_port_open 127.0.0.1 "${CLICKHOUSE_NATIVE_PORT}"; then
    echo "Port ${CLICKHOUSE_NATIVE_PORT} is already in use, but dc-clickhouse is not running." >&2
    echo "Standalone deployment would conflict with an existing ClickHouse or another service." >&2
    echo "Use ./deploy-with-external-clickhouse.sh if you already have ClickHouse." >&2
    exit 1
  fi
}

main() {
  case "${1:-}" in
    -h|--help)
      usage
      exit 0
      ;;
    "")
      ;;
    *)
      echo "Unexpected argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac

  check_file "${ENV_FILE}"
  check_file "${DEPLOY_SCRIPT}"

  local backup_file
  backup_file="${ENV_FILE}.bak.standalone.$(date '+%Y%m%d%H%M%S')"
  cp -a "${ENV_FILE}" "${backup_file}"

  set_env_value CLICKHOUSE_MODE embedded
  set_env_value CLICKHOUSE_HOST 127.0.0.1
  load_env
  check_embedded_ports

  echo "Using embedded ClickHouse deployment."
  echo "Backed up .env.prod to ${backup_file}"
  exec "${DEPLOY_SCRIPT}"
}

main "$@"
