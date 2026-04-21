#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
DEPLOY_SCRIPT="${ROOT_DIR}/deploy.sh"

usage() {
  cat <<'USAGE'
Usage:
  ./deploy-with-external-clickhouse.sh

Deploy the application stack while using an existing ClickHouse instance.

This script:
  1. backs up .env.prod
  2. sets CLICKHOUSE_MODE=external
  3. keeps CLICKHOUSE_HOST, ports, username, and password from .env.prod
  4. delegates to ./deploy.sh

It does not start the ClickHouse container and does not mutate an existing database.
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
  : "${CLICKHOUSE_HOST:?CLICKHOUSE_HOST is required}"
  : "${CLICKHOUSE_HTTP_PORT:?CLICKHOUSE_HTTP_PORT is required}"
  : "${CLICKHOUSE_DB_NAME:?CLICKHOUSE_DB_NAME is required}"
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
  backup_file="${ENV_FILE}.bak.external.$(date '+%Y%m%d%H%M%S')"
  cp -a "${ENV_FILE}" "${backup_file}"

  set_env_value CLICKHOUSE_MODE external
  load_env

  echo "Using external ClickHouse deployment."
  echo "ClickHouse target: ${CLICKHOUSE_HOST}:${CLICKHOUSE_HTTP_PORT}/${CLICKHOUSE_DB_NAME}"
  echo "Backed up .env.prod to ${backup_file}"
  exec "${DEPLOY_SCRIPT}"
}

main "$@"
