#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORDER_CLUSTER_DEV_ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
LAST_SUCCESSFUL_MANIFEST="${ORDER_CLUSTER_DEV_ROOT}/deploy-state/last-successful.env"
ROLLBACK_MANIFEST="${ORDER_CLUSTER_DEV_ROOT}/deploy-state/rollback.env"

log() { printf '[order-cluster-rollback] %s\n' "$*"; }
die() { printf '[order-cluster-rollback] ERROR: %s\n' "$*" >&2; exit 1; }

manifest_value() {
  local file="$1" key="$2"
  sudo awk -F= -v key="${key}" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "${file}"
}

sudo test -r "${LAST_SUCCESSFUL_MANIFEST}" ||
  die "last successful manifest is unavailable: ${LAST_SUCCESSFUL_MANIFEST}"
last_order_image="$(manifest_value "${LAST_SUCCESSFUL_MANIFEST}" ORDERSVR_CLUSTER_DEV_IMAGE)"
last_gw_image="$(manifest_value "${LAST_SUCCESSFUL_MANIFEST}" GW_CLUSTER_DEV_IMAGE)"
current_order_image="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-ordersvr-a 2>/dev/null || true)"
current_gw_image="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-gateway 2>/dev/null || true)"

if [[ "${current_order_image}" == "${last_order_image}" && "${current_gw_image}" == "${last_gw_image}" ]]; then
  sudo test -r "${ROLLBACK_MANIFEST}" || die "rollback manifest is unavailable: ${ROLLBACK_MANIFEST}"
  target_manifest="${ROLLBACK_MANIFEST}"
  reason="current deployment is healthy and matches last-successful"
else
  target_manifest="${LAST_SUCCESSFUL_MANIFEST}"
  reason="current deployment is absent, partial or differs from last-successful"
fi

order_image="$(manifest_value "${target_manifest}" ORDERSVR_CLUSTER_DEV_IMAGE)"
gw_image="$(manifest_value "${target_manifest}" GW_CLUSTER_DEV_IMAGE)"
[[ "${order_image}" =~ ^ghcr\.io/bliplink/ordersvr:cluster-dev-[0-9a-f]{7,40}$ ]] ||
  die "invalid OrderSvr rollback image: ${order_image}"
[[ "${gw_image}" =~ ^ghcr\.io/bliplink/ordersvr:gw-cluster-dev-[0-9a-f]{7,40}$ ]] ||
  die "invalid GW rollback image: ${gw_image}"

log "Selected ${target_manifest}: ${reason}"
log "Restoring immutable image pair OrderSvr=${order_image}, GW=${gw_image}"
export ORDER_CLUSTER_DEV_ROOT
export ORDERSVR_CLUSTER_DEV_IMAGE="${order_image}"
export GW_CLUSTER_DEV_IMAGE="${gw_image}"
exec "${SCRIPT_DIR}/deploy-order-cluster-dev.sh"
