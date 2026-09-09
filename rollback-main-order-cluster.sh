#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/data/dc-saas-runtime}"
STATE_DIR="${DEPLOY_ROOT}/deploy-state/order-cluster"
BASELINE_ENV="${STATE_DIR}/standalone.env"
PAUSE_MARKER="${STATE_DIR}/auto-update-paused-by-cluster"

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root or with sudo.' >&2; exit 1; }
[[ -r "${BASELINE_ENV}" ]] || { echo "Missing rollback environment: ${BASELINE_ENV}" >&2; exit 1; }

install -m 0600 "${BASELINE_ENV}" "${ENV_FILE}"
docker rm -f dc-saas-ordersvr-b >/dev/null 2>&1 || true
ENV_FILE="${ENV_FILE}" "${SCRIPT_DIR}/deploy-saas.sh" --skip-host-prepare

pause_file="${SAAS_AUTO_UPDATE_PAUSE_FILE:-${DEPLOY_ROOT}/auto-update.paused}"
if [[ -e "${PAUSE_MARKER}" ]]; then
  rm -f -- "${pause_file}" "${PAUSE_MARKER}"
fi
printf '[order-cluster-rollback] Standalone OrderSvr restored. Cluster data was retained.\n'
