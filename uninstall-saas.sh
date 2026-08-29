#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
LOCK_FILE="${SAAS_AUTO_UPDATE_LOCK_FILE:-/tmp/dc-saas-auto-update.lock}"
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

Without flags, remove only containers whose names start with dc-saas-, plus
this Compose project's networks and volumes, while preserving MySQL,
ClickHouse, ZooKeeper, logs, generated config, and images.

--purge-data    Also permanently remove /opt/dc-saas-runtime.
--purge-images  Also remove images referenced by any dc-saas-* container.

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
command -v flock >/dev/null 2>&1 || die "flock is required."
exec 8>"${LOCK_FILE}"
flock -n 8 || die "Another SaaS deploy, uninstall, or auto-update run holds ${LOCK_FILE}."

if [[ -x "${SCRIPT_DIR}/install-auto-update-cron.sh" ]]; then
  "${SCRIPT_DIR}/install-auto-update-cron.sh" --remove
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" "$@"
}

discover_saas_container_ids() {
  docker ps -aq --filter 'name=^/dc-saas-' || true
  docker ps -aq --filter 'label=dc.saas.role' || true

  # Some ad-hoc Playwright/load-test runs predate the dc.saas.role label and
  # received a random Docker name.  Select them only when a bind mount proves
  # that they belong to this deployment's tests or isolated runtime root.
  for container_id in $(docker ps -aq); do
    while IFS= read -r mount_source; do
      case "${mount_source}" in
        "${DEPLOY_ROOT}"|"${DEPLOY_ROOT}/"*|"${SCRIPT_DIR}/tests"|"${SCRIPT_DIR}/tests/"*)
          printf '%s\n' "${container_id}"
          break
          ;;
      esac
    done < <(docker inspect --format '{{range .Mounts}}{{println .Source}}{{end}}' "${container_id}" 2>/dev/null || true)
  done
}

saas_container_ids="$(discover_saas_container_ids | sort -u)"
image_ids=""
image_refs=""
if [[ "${PURGE_IMAGES}" == "true" ]]; then
  image_ids="$(
    {
      compose images -q 2>/dev/null || true
      if [[ -n "${saas_container_ids}" ]]; then
        for container_id in ${saas_container_ids}; do
          docker inspect --format '{{.Image}}' "${container_id}" 2>/dev/null || true
        done
      fi
    } | sort -u
  )"
  if [[ -n "${image_ids}" ]]; then
    image_refs="$(
      for image_id in ${image_ids}; do
        docker image inspect --format '{{range .RepoTags}}{{println .}}{{end}}' "${image_id}" 2>/dev/null || true
      done | grep -v '<none>' | sort -u || true
    )"
  fi
fi

compose down --volumes --remove-orphans

# Rollback and browser-acceptance containers are deliberately outside the
# current Compose model.  Keep the removal boundary exact and auditable by
# selecting only the reserved dc-saas-* name prefix.
remaining_container_ids="$(discover_saas_container_ids | sort -u)"
if [[ -n "${remaining_container_ids}" ]]; then
  # shellcheck disable=SC2086
  docker rm -f ${remaining_container_ids}
fi

remaining_network_ids="$({
  docker network ls -q --filter 'label=com.docker.compose.project=dc-saas' || true
  docker network ls --format '{{.ID}} {{.Name}}' | awk '$2 ~ /^dc-saas-/ {print $1}' || true
} | sort -u)"
if [[ -n "${remaining_network_ids}" ]]; then
  # shellcheck disable=SC2086
  docker network rm ${remaining_network_ids} || true
fi

remaining_volume_names="$({
  docker volume ls -q --filter 'label=com.docker.compose.project=dc-saas' || true
  docker volume ls -q | grep -E '^dc-saas-' || true
} | sort -u)"
if [[ -n "${remaining_volume_names}" ]]; then
  # shellcheck disable=SC2086
  docker volume rm ${remaining_volume_names} || true
fi

log "Removed all dc-saas-* containers and this Compose project's networks and volumes."

if [[ "${PURGE_IMAGES}" == "true" && -n "${image_refs}" ]]; then
  # Remove every tag pointing at a captured SaaS image before deleting by ID;
  # Docker otherwise rejects IDs that have multiple repository references.
  # shellcheck disable=SC2086
  docker image rm ${image_refs} || true
fi

if [[ "${PURGE_IMAGES}" == "true" && -n "${image_ids}" ]]; then
  # shellcheck disable=SC2086
  docker image rm ${image_ids} || true
  log "Removed captured SaaS image references and unreferenced image layers."
fi

if [[ "${PURGE_DATA}" == "true" ]]; then
  resolved_root="$(readlink -m "${DEPLOY_ROOT}")"
  [[ "${resolved_root}" == "/opt/dc-saas-runtime" ]] ||
    die "Refusing data purge outside the exact validated root /opt/dc-saas-runtime (resolved: ${resolved_root})."
  [[ ! -L "${DEPLOY_ROOT}" ]] || die "Refusing to purge a symbolic-link runtime root."
  rm -rf --one-file-system "${resolved_root}"
  log "Permanently removed ${resolved_root}. This data is not recoverable unless separately backed up."

  resolved_build_root="$(readlink -m "${BUILD_ROOT:-/opt/dc-saas-build}")"
  [[ "${resolved_build_root}" == "/opt/dc-saas-build" ]] ||
    die "Refusing build-cache purge outside /opt/dc-saas-build (resolved: ${resolved_build_root})."
  [[ ! -L "${resolved_build_root}" ]] || die "Refusing to purge a symbolic-link build root."
  rm -rf --one-file-system "${resolved_build_root}"
  log "Removed the isolated SaaS source and Maven build cache at ${resolved_build_root}."
else
  log "Preserved runtime data and generated config at ${DEPLOY_ROOT}."
fi
