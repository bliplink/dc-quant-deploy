#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
PULL_SCRIPT="${ROOT_DIR}/pull-images.sh"
RESTART_SCRIPT="${ROOT_DIR}/restart-service.sh"

DRY_RUN=false
SERVICE=""

usage() {
  cat <<'USAGE'
Usage:
  ./auto-update-service.sh <service> [--dry-run]

Behavior:
  - Pull the configured image tag for one service
  - Compare image IDs before and after pull
  - Restart the service only when the image ID changes
  - If restart validation fails, retag the previous image ID back to the configured image ref and retry once

Examples:
  ./auto-update-service.sh indsvr
  ./auto-update-service.sh web
  ./auto-update-service.sh indsvr --dry-run
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

run() {
  echo "+ $*"
  if [[ "${DRY_RUN}" != "true" ]]; then
    "$@"
  fi
}

load_env() {
  require_file "${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
}

normalize_service() {
  case "$1" in
    GW|gw)
      echo "gateway"
      ;;
    gateway|mdsvr|apssvr|quantsvr|indsvr|simsvr|batchsvr|web|zookeeper|clickhouse)
      echo "$1"
      ;;
    *)
      echo ""
      ;;
  esac
}

service_image_ref() {
  case "$1" in
    gateway)
      echo "ghcr.io/bliplink/gw:${GW_TAG}"
      ;;
    mdsvr)
      echo "ghcr.io/bliplink/mdsvr:${MDSVR_TAG}"
      ;;
    apssvr)
      echo "ghcr.io/bliplink/apssvr:${APSSVR_TAG}"
      ;;
    quantsvr)
      echo "ghcr.io/bliplink/quantsvr:${QUANTSVR_TAG}"
      ;;
    indsvr)
      echo "ghcr.io/bliplink/indsvr:${INDSVR_TAG}"
      ;;
    simsvr)
      echo "ghcr.io/SKT-Walter/simsvr:${SIMSVR_TAG}"
      ;;
    batchsvr)
      echo "ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}"
      ;;
    web)
      echo "ghcr.io/SKT-Walter/web:${WEB_TAG}"
      ;;
    zookeeper)
      echo "ghcr.io/bliplink/zookeeper:${ZOOKEEPER_TAG}"
      ;;
    clickhouse)
      echo "clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}"
      ;;
    *)
      return 1
      ;;
  esac
}

image_id_or_empty() {
  local image_ref="$1"
  docker image inspect "${image_ref}" --format '{{.Id}}' 2>/dev/null || true
}

main() {
  require_command docker
  require_file "${PULL_SCRIPT}"
  require_file "${RESTART_SCRIPT}"
  load_env

  local compose_service
  compose_service="$(normalize_service "${SERVICE}")"
  if [[ -z "${compose_service}" ]]; then
    echo "Unsupported service: ${SERVICE}" >&2
    exit 1
  fi

  local image_ref
  image_ref="$(service_image_ref "${compose_service}")"
  if [[ -z "${image_ref}" ]]; then
    echo "Image ref not found for service: ${compose_service}" >&2
    exit 1
  fi

  local before_id after_id
  before_id="$(image_id_or_empty "${image_ref}")"

  echo "Service: ${compose_service}"
  echo "Image ref: ${image_ref}"
  echo "Before image ID: ${before_id:-<missing>}"

  run bash "${PULL_SCRIPT}" "${compose_service}"

  after_id="$(image_id_or_empty "${image_ref}")"
  echo "After image ID: ${after_id:-<missing>}"

  if [[ -z "${after_id}" ]]; then
    echo "Image pull did not leave a local image: ${image_ref}" >&2
    exit 1
  fi

  if [[ "${before_id}" == "${after_id}" ]]; then
    echo "No image change detected for ${compose_service}; skip restart."
    exit 0
  fi

  echo "Image changed for ${compose_service}; restarting."
  if run bash "${RESTART_SCRIPT}" "${compose_service}"; then
    echo "Auto update completed for ${compose_service}."
    exit 0
  fi

  if [[ -n "${before_id}" ]]; then
    echo "Restart failed; rolling back ${compose_service} to previous local image ID ${before_id}."
    run docker tag "${before_id}" "${image_ref}"
    run bash "${RESTART_SCRIPT}" "${compose_service}"
    echo "Rollback completed for ${compose_service}."
    exit 1
  fi

  echo "Restart failed and no previous image ID is available for rollback." >&2
  exit 1
}

main "$@"
