#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
MANIFEST_DIR="${MANIFEST_DIR:-${SCRIPT_DIR}/.cluster-dev}"
ORDER_MANIFEST="${ORDER_MANIFEST:-${MANIFEST_DIR}/ordersvr-build-manifest.env}"
GW_MANIFEST="${GW_MANIFEST:-${MANIFEST_DIR}/gw-build-manifest.env}"

log() {
  printf '[cluster-dev-deploy] %s\n' "$*"
}

die() {
  printf '[cluster-dev-deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || die "Run as root or with sudo"
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -r "${ORDER_MANIFEST}" ]] || die "Cannot read ${ORDER_MANIFEST}"
[[ -r "${GW_MANIFEST}" ]] || die "Cannot read ${GW_MANIFEST}"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
# shellcheck disable=SC1090
. "${ORDER_MANIFEST}"
ORDERSVR_CLUSTER_DEV_IMAGE="${ORDERSVR_IMAGE:?ORDERSVR_IMAGE is missing from build manifest}"
# shellcheck disable=SC1090
. "${GW_MANIFEST}"
GW_CLUSTER_DEV_IMAGE="${GW_IMAGE:?GW_IMAGE is missing from build manifest}"
export ORDERSVR_CLUSTER_DEV_IMAGE GW_CLUSTER_DEV_IMAGE
set +a

: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
PAUSE_FILE="${SAAS_AUTO_UPDATE_PAUSE_FILE:-${DEPLOY_ROOT}/auto-update.paused}"
COMPOSE_ARGS=(
  --env-file "${ENV_FILE}"
  -f "${SCRIPT_DIR}/compose.yaml"
  -f "${SCRIPT_DIR}/compose.cluster-dev-images.yaml"
)

docker image inspect "${ORDERSVR_CLUSTER_DEV_IMAGE}" >/dev/null 2>&1 ||
  die "Local OrderSvr image is missing: ${ORDERSVR_CLUSTER_DEV_IMAGE}"
docker image inspect "${GW_CLUSTER_DEV_IMAGE}" >/dev/null 2>&1 ||
  die "Local GW image is missing: ${GW_CLUSTER_DEV_IMAGE}"
docker compose "${COMPOSE_ARGS[@]}" config --quiet

install -d -m 0750 "$(dirname "${PAUSE_FILE}")"
{
  printf 'paused_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'reason=cluster-dev-local-images\n'
  printf 'ordersvr_image=%s\n' "${ORDERSVR_CLUSTER_DEV_IMAGE}"
  printf 'gw_image=%s\n' "${GW_CLUSTER_DEV_IMAGE}"
} > "${PAUSE_FILE}"

log "Automatic GHCR deployment paused: ${PAUSE_FILE}"
log "Deploying GW and OrderSvr local images"
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps gateway ordersvr

running_order="$(docker inspect dc-saas-ordersvr --format '{{.Config.Image}}')"
running_gw="$(docker inspect dc-saas-gateway --format '{{.Config.Image}}')"
[[ "${running_order}" == "${ORDERSVR_CLUSTER_DEV_IMAGE}" ]] ||
  die "OrderSvr is running unexpected image ${running_order}"
[[ "${running_gw}" == "${GW_CLUSTER_DEV_IMAGE}" ]] ||
  die "GW is running unexpected image ${running_gw}"

log "Local development images are running"
log "Run ./resume-saas-auto-update.sh only after restoring registry images"
