#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"

[[ "${1:-}" == "--confirm-registry-images-restored" ]] || {
  printf '[cluster-dev-deploy] ERROR: restore registry GW/OrderSvr images, then run %s --confirm-registry-images-restored\n' "$0" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || {
  printf '[cluster-dev-deploy] ERROR: run as root or with sudo\n' >&2
  exit 1
}
[[ -r "${ENV_FILE}" ]] || {
  printf '[cluster-dev-deploy] ERROR: cannot read %s\n' "${ENV_FILE}" >&2
  exit 1
}

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"

PAUSE_FILE="${SAAS_AUTO_UPDATE_PAUSE_FILE:-${DEPLOY_ROOT}/auto-update.paused}"
expected_order="${ORDERSVR_IMAGE_REPOSITORY:-ghcr.io/bliplink/ordersvr}:${ORDERSVR_TAG:-saas-crypto}"
expected_gw="${GW_IMAGE_REPOSITORY:-ghcr.io/bliplink/gw}:${GW_TAG:-saas-crypto}"
running_order="$(docker inspect dc-saas-ordersvr --format '{{.Config.Image}}' 2>/dev/null || true)"
running_gw="$(docker inspect dc-saas-gateway --format '{{.Config.Image}}' 2>/dev/null || true)"
[[ "${running_order}" == "${expected_order}" ]] || {
  printf '[cluster-dev-deploy] ERROR: OrderSvr is still using %s, expected %s\n' "${running_order}" "${expected_order}" >&2
  exit 1
}
[[ "${running_gw}" == "${expected_gw}" ]] || {
  printf '[cluster-dev-deploy] ERROR: GW is still using %s, expected %s\n' "${running_gw}" "${expected_gw}" >&2
  exit 1
}
if [[ -f "${PAUSE_FILE}" ]]; then
  rm -f -- "${PAUSE_FILE}"
  printf '[cluster-dev-deploy] Automatic deployment resumed; pause marker removed: %s\n' "${PAUSE_FILE}"
else
  printf '[cluster-dev-deploy] Automatic deployment was not paused: %s\n' "${PAUSE_FILE}"
fi
