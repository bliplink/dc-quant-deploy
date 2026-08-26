#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
PURGE_DATA="false"
PURGE_IMAGES="false"

log() {
  printf '[saas-uninstall] %s\n' "$*"
}

die() {
  printf '[saas-uninstall] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: sudo ./uninstall-saas.sh [--purge-data] [--purge-images]

Without flags, remove only DC SaaS containers and its Compose network while
preserving MySQL, ClickHouse, ZooKeeper, logs, generated config, and images.

--purge-data    Also permanently remove /opt/dc-saas-runtime.
--purge-images  Also remove images referenced by this SaaS Compose project.

The independent quantitative-trading and legacy /opt/sumscope services are
never selected by this script.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --purge-data)
      PURGE_DATA="true"
      ;;
    --purge-images)
      PURGE_IMAGES="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ "${EUID}" -eq 0 ]] || die "Run as root or with sudo."
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" "$@"
}

image_ids=""
if [[ "${PURGE_IMAGES}" == "true" ]]; then
  image_ids="$(compose images -q 2>/dev/null | sort -u || true)"
fi

compose down --remove-orphans
log "Removed only dc-saas containers and its Compose network."

if [[ "${PURGE_IMAGES}" == "true" && -n "${image_ids}" ]]; then
  # shellcheck disable=SC2086
  docker image rm ${image_ids} || true
  log "Removed unreferenced SaaS images."
fi

if [[ "${PURGE_DATA}" == "true" ]]; then
  resolved_root="$(readlink -m "${DEPLOY_ROOT}")"
  [[ "${resolved_root}" == "/opt/dc-saas-runtime" ]] ||
    die "Refusing data purge outside the exact validated root /opt/dc-saas-runtime (resolved: ${resolved_root})."
  [[ ! -L "${DEPLOY_ROOT}" ]] || die "Refusing to purge a symbolic-link runtime root."
  rm -rf --one-file-system "${resolved_root}"
  log "Permanently removed ${resolved_root}. This data is not recoverable unless separately backed up."
else
  log "Preserved runtime data and generated config at ${DEPLOY_ROOT}."
fi
