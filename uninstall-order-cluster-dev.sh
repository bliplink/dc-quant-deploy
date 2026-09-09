#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="dc-saas-order-cluster-dev"
ORDER_CLUSTER_DEV_ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
export ORDER_CLUSTER_DEV_ROOT

sudo -E docker compose -p "${PROJECT_NAME}" -f "${SCRIPT_DIR}/compose.order-cluster-dev.yaml" down --remove-orphans

if [[ "${1:-}" == "--purge-data" ]]; then
  [[ "${2:-}" == "CONFIRM_ORDER_CLUSTER_DEV" ]] || {
    printf 'Refusing data removal; use --purge-data CONFIRM_ORDER_CLUSTER_DEV\n' >&2
    exit 1
  }
  resolved="$(readlink -f -- "${ORDER_CLUSTER_DEV_ROOT}")"
  [[ "${resolved}" == /data/dc-saas-order-cluster-dev ]] || {
    printf 'Refusing unexpected purge path: %s\n' "${resolved}" >&2
    exit 1
  }
  sudo rm -rf -- "${resolved}"
  printf '[order-cluster-dev] removed %s (not recoverable)\n' "${resolved}"
else
  printf '[order-cluster-dev] containers removed; evidence and data retained at %s\n' "${ORDER_CLUSTER_DEV_ROOT}"
fi
