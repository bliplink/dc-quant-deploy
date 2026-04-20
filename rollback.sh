#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
LAST_BACKUP_FILE="${ROOT_DIR}/.last_backup"

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

load_env() {
  [ -f "${ENV_FILE}" ] || {
    echo "Missing ${ENV_FILE}" >&2
    exit 1
  }
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
}

restore_control() {
  [ -f "${LAST_BACKUP_FILE}" ] || {
    echo "Missing ${LAST_BACKUP_FILE}" >&2
    exit 1
  }
  local backup_dir
  backup_dir="$(cat "${LAST_BACKUP_FILE}")"
  [ -d "${backup_dir}/control" ] || {
    echo "Backup control directory not found: ${backup_dir}/control" >&2
    exit 1
  }

  rm -rf "${DEPLOY_ROOT}/control"
  mkdir -p "${DEPLOY_ROOT}"
  cp -a "${backup_dir}/control" "${DEPLOY_ROOT}/control"
}

restart_legacy_services() {
  if [ -x "${DEPLOY_ROOT}/scripts/start" ]; then
    "${DEPLOY_ROOT}/scripts/start" "${SERVICE_NAMES[@]}"
  fi
}

main() {
  load_env
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down || true
  restore_control
  restart_legacy_services
  echo "Rollback completed. ClickHouse data in ${DEPLOY_ROOT}/clickhouse/data was preserved."
}

main "$@"
