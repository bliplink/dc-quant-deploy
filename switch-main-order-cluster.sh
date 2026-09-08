#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/data/dc-saas-runtime}"
STATE_DIR="${DEPLOY_ROOT}/deploy-state/order-cluster"
BASELINE_ENV="${STATE_DIR}/standalone.env"
PAUSE_MARKER="${STATE_DIR}/auto-update-paused-by-cluster"

log() { printf '[order-cluster-switch] %s\n' "$*"; }
die() { printf '[order-cluster-switch] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || die 'Run as root or with sudo.'
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"

for name in ORDER_CLUSTER_GW_IMAGE ORDER_CLUSTER_ORDERSVR_IMAGE ORDER_CLUSTER_MDSVR_IMAGE \
  ORDER_CLUSTER_TRADESVR_IMAGE ORDER_CLUSTER_LIQSVR_IMAGE; do
  [[ "${!name:-}" == ghcr.io/*:cluster-dev-* ]] || die "${name} must be an immutable cluster-dev image reference"
done

deploy_args=(--skip-host-prepare)
if [[ "${ORDER_CLUSTER_LOCAL_IMAGES:-false}" == "true" ]]; then
  deploy_args+=(--skip-pull)
  for name in ORDER_CLUSTER_GW_IMAGE ORDER_CLUSTER_ORDERSVR_IMAGE ORDER_CLUSTER_MDSVR_IMAGE \
    ORDER_CLUSTER_TRADESVR_IMAGE ORDER_CLUSTER_LIQSVR_IMAGE; do
    docker image inspect "${!name}" >/dev/null 2>&1 ||
      die "Local cluster image is missing: ${!name}"
  done
  log 'Using locally built immutable cluster images; registry pull is disabled for this cutover.'
fi

set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*$|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

set_image() {
  local prefix="$1" image="$2" repository tag
  repository="${image%:*}"
  tag="${image##*:}"
  set_env "${prefix}_IMAGE_REPOSITORY" "${repository}"
  set_env "${prefix}_TAG" "${tag}"
}

install -d -m 0700 "${STATE_DIR}"
if [[ ! -e "${BASELINE_ENV}" ]]; then
  install -m 0600 "${ENV_FILE}" "${BASELINE_ENV}"
  log "Saved standalone rollback environment to ${BASELINE_ENV}"
fi

pause_file="${SAAS_AUTO_UPDATE_PAUSE_FILE:-${DEPLOY_ROOT}/auto-update.paused}"
if [[ ! -e "${pause_file}" ]]; then
  printf 'OrderSvr cluster development cutover is active.\n' > "${pause_file}"
  chmod 0600 "${pause_file}"
  : > "${PAUSE_MARKER}"
fi

set_image GW "${ORDER_CLUSTER_GW_IMAGE}"
set_image ORDERSVR "${ORDER_CLUSTER_ORDERSVR_IMAGE}"
set_image MDSVR "${ORDER_CLUSTER_MDSVR_IMAGE}"
set_image TRADESVR "${ORDER_CLUSTER_TRADESVR_IMAGE}"
set_image LIQSVR "${ORDER_CLUSTER_LIQSVR_IMAGE}"
set_env ORDER_CLUSTER_ENABLED true
set_env ORDERSVR_CONFIG_NAME OrderSvrA
set_env COMPOSE_PROFILES order-cluster
set_env ORDERSVR_B_GW_PORT "${ORDERSVR_B_GW_PORT:-33041}"
set_env ORDERSVR_A_REPLICATION_PORT "${ORDERSVR_A_REPLICATION_PORT:-19121}"
set_env ORDERSVR_B_REPLICATION_PORT "${ORDERSVR_B_REPLICATION_PORT:-19122}"

log 'Deploying the main SaaS stack with OrderSvr A/B enabled.'
if ! ENV_FILE="${ENV_FILE}" "${SCRIPT_DIR}/deploy-saas.sh" "${deploy_args[@]}"; then
  log 'Cluster deployment failed; restoring the standalone environment.'
  install -m 0600 "${BASELINE_ENV}" "${ENV_FILE}"
  docker rm -f dc-saas-ordersvr-b >/dev/null 2>&1 || true
  ENV_FILE="${ENV_FILE}" "${SCRIPT_DIR}/deploy-saas.sh" --skip-host-prepare --skip-pull ||
    die 'Automatic standalone rollback also failed; manual recovery is required.'
  die 'Cluster deployment failed and the standalone stack was restored.'
fi
log 'OrderSvr A/B cutover completed.'
