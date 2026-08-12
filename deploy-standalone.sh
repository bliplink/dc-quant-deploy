#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
DEPLOY_SCRIPT="${ROOT_DIR}/deploy.sh"
ENV_EXAMPLE="${ROOT_DIR}/.env.standalone.example"
CONTROL_DIR="${ROOT_DIR}/control.prod"
CONTROL_EXAMPLE_DIR="${ROOT_DIR}/control.prod.example"
VALIDATE_ENV_SCRIPT="${ROOT_DIR}/validate-env.sh"

usage() {
  cat <<'USAGE'
Usage:
  ./deploy-standalone.sh

Deploy the full stack from scratch, including the embedded ClickHouse container.

This script:
  1. creates .env.prod from .env.standalone.example when missing
  2. creates control.prod defaults when missing
  3. backs up .env.prod
  4. sets CLICKHOUSE_MODE=embedded
  5. sets CLICKHOUSE_HOST=127.0.0.1
  6. checks that ClickHouse ports are not already occupied by another process
  7. delegates to ./deploy.sh
USAGE
}

check_file() {
  [ -f "$1" ] || {
    echo "Missing required file: $1" >&2
    exit 1
  }
}

copy_if_missing() {
  local src="$1"
  local dst="$2"

  if [ ! -e "${dst}" ]; then
    cp -a "${src}" "${dst}"
  fi
}

prepare_defaults() {
  check_file "${ENV_EXAMPLE}"
  check_file "${CONTROL_EXAMPLE_DIR}/ATSConfig.ini"
  check_file "${CONTROL_EXAMPLE_DIR}/DBPoolConfig.ini"
  check_file "${CONTROL_EXAMPLE_DIR}/jaas.ini"
  check_file "${CONTROL_EXAMPLE_DIR}/dc.dat"

  copy_if_missing "${ENV_EXAMPLE}" "${ENV_FILE}"

  mkdir -p "${CONTROL_DIR}"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/ATSConfig.ini" "${CONTROL_DIR}/ATSConfig.ini"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/DBPoolConfig.ini" "${CONTROL_DIR}/DBPoolConfig.ini"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/jaas.ini" "${CONTROL_DIR}/jaas.ini"
  copy_if_missing "${CONTROL_EXAMPLE_DIR}/dc.dat" "${CONTROL_DIR}/dc.dat"

  if [ -d "${CONTROL_EXAMPLE_DIR}/overrides" ] && [ ! -e "${CONTROL_DIR}/overrides" ]; then
    cp -a "${CONTROL_EXAMPLE_DIR}/overrides" "${CONTROL_DIR}/overrides"
  fi
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

set_env_value_if_missing() {
  local key="$1"
  local value="$2"

  if ! grep -q "^${key}=" "${ENV_FILE}"; then
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
    return 0
  fi

  od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

ensure_clickhouse_password() {
  local current_password
  current_password="$(
    sed -n 's/^CLICKHOUSE_PASSWORD=//p' "${ENV_FILE}" | tail -n 1
  )"
  if [[ -n "${current_password}" ]]; then
    return 0
  fi

  set_env_value CLICKHOUSE_PASSWORD "$(generate_secret)"
  echo "Generated a non-empty ClickHouse password in .env.prod."
}

load_env() {
  check_file "${VALIDATE_ENV_SCRIPT}"
  bash "${VALIDATE_ENV_SCRIPT}" "${ENV_FILE}"
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

  check_file "${DEPLOY_SCRIPT}"
  prepare_defaults

  local backup_file
  backup_file="${ENV_FILE}.bak.standalone.$(date '+%Y%m%d%H%M%S')"
  cp -a "${ENV_FILE}" "${backup_file}"

  set_env_value CLICKHOUSE_MODE embedded
  set_env_value CLICKHOUSE_HOST 127.0.0.1
  set_env_value_if_missing \
    CLICKHOUSE_IMAGE_REPOSITORY \
    docker.m.daocloud.io/clickhouse/clickhouse-server
  set_env_value_if_missing CLICKHOUSE_APPLY_OPTIONAL_SEED true
  ensure_clickhouse_password
  load_env
  check_embedded_ports

  echo "Using embedded ClickHouse deployment."
  echo "Backed up .env.prod to ${backup_file}"
  exec "${DEPLOY_SCRIPT}"
}

main "$@"
