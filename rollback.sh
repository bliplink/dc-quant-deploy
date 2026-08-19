#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${ROOT_DIR}/generate-compose-overrides.sh"
LAST_BACKUP_FILE="${ROOT_DIR}/.last_backup"
VALIDATE_ENV_SCRIPT="${ROOT_DIR}/validate-env.sh"

APP_SERVICES=(
  gateway
  loginsvr
  mdsvr
  apssvr
  quantsvr
  indsvr
  customindsvr
  simsvr
  batchsvr
  web
)

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
  [ -f "${VALIDATE_ENV_SCRIPT}" ] || {
    echo "Missing ${VALIDATE_ENV_SCRIPT}" >&2
    exit 1
  }
  bash "${VALIDATE_ENV_SCRIPT}" "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
}

generate_compose_overrides() {
  [ -f "${GENERATE_OVERRIDES_SCRIPT}" ] || {
    echo "Missing ${GENERATE_OVERRIDES_SCRIPT}" >&2
    exit 1
  }
  bash "${GENERATE_OVERRIDES_SCRIPT}" "${ENV_FILE}" "${OVERRIDE_FILE}"
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
  restore_control
  generate_compose_overrides
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -f "${OVERRIDE_FILE}" \
    up -d --force-recreate --no-deps "${APP_SERVICES[@]}"
  restart_legacy_services
  echo "Rollback completed. Containerized services were restored and ClickHouse data in ${DEPLOY_ROOT}/data/clickhouse was preserved."
}

main "$@"
