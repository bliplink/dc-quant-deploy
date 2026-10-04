#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="${ROOT}/release/saas-crypto-images.env"

[[ -f "${LOCK}" ]] || { echo "missing release image lock: ${LOCK}" >&2; exit 1; }

# shellcheck disable=SC1090
source "${LOCK}"

[[ "${IMAGE_SOURCE:-}" == "registry" ]] || {
  echo "IMAGE_SOURCE must be registry in release lock" >&2
  exit 1
}

required=(
  GW LOGINSVR MDSVR APSSVR ORDERSVR PROJECTIONSVR TRADESVR
  LIQSVR MANAGERSVR ADMINSVR ROBOTSVR TRADE_WEB TENANT_WEB PLATFORM_WEB
)

for prefix in "${required[@]}"; do
  repo_var="${prefix}_IMAGE_REPOSITORY"
  tag_var="${prefix}_TAG"
  repo="${!repo_var:-}"
  tag="${!tag_var:-}"

  [[ "${repo}" == ghcr.io/bliplink/* ]] || {
    echo "${repo_var} must use ghcr.io/bliplink, got: ${repo}" >&2
    exit 1
  }
  [[ "${repo}" != local/* ]] || {
    echo "${repo_var} must not use local images" >&2
    exit 1
  }
  [[ "${tag}" == sha-* ]] || {
    echo "${tag_var} must be immutable sha-* tag, got: ${tag}" >&2
    exit 1
  }
  [[ "${tag}" != "saas-crypto" ]] || {
    echo "${tag_var} must not use moving saas-crypto tag" >&2
    exit 1
  }
done

echo "[release-image-lock] PASS: ${#required[@]} immutable registry images"
