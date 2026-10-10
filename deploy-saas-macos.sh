#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -s)" == "Darwin" ]] || { echo "[saas-macos] ERROR: this entrypoint is for macOS only." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "[saas-macos] ERROR: Docker CLI with a working Docker Engine (Colima or Docker Desktop) is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[saas-macos] ERROR: docker compose is required." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "[saas-macos] ERROR: Docker daemon is unavailable (start Colima or Docker Desktop)." >&2; exit 1; }

ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
# Dedicated cold-reset entrypoint. Read-only planning is the default; any
# destructive stage requires a specific explicit token and owns its own lock.
if [[ "${1:-}" == "reset" ]]; then
  shift
  exec python3 "${SCRIPT_DIR}/scripts/mac-saas-reset.py" "$@"
fi
if [[ "${1:-}" == "--check" ]]; then
  shift
  [[ "$#" == 0 || ( "$#" == 1 && "$1" == "--full-cluster" ) ]] || {
    echo "[saas-macos] ERROR: --check accepts only --full-cluster." >&2; exit 2;
  }
  [[ -f "$ENV_FILE" ]] || { echo "[saas-macos] ERROR: missing env file for read-only preflight." >&2; exit 2; }
  [[ -f "${RELEASE_IMAGE_LOCK:-${SCRIPT_DIR}/release/saas-crypto-images.env}" ]] || {
    echo "[saas-macos] ERROR: missing immutable release lock file." >&2; exit 2;
  }
  if [[ "${1:-}" == "--full-cluster" ]]; then
    COMPOSE_PROFILES=order-cluster,order-cluster-c,md-cluster,md-cluster-c,trade-cluster \
      docker compose --env-file "$ENV_FILE" -f "${SCRIPT_DIR}/compose.yaml" config --quiet || exit 2
    echo "[saas-macos] Verified full-cluster Compose profiles: Order A/B/C, MD A/B/C, Trade A/B."
  else
    docker compose --env-file "$ENV_FILE" -f "${SCRIPT_DIR}/compose.yaml" config --quiet || exit 2
  fi
  printf '[saas-macos] read-only configuration valid, Docker context=%s\n' "$(docker context show)"
  if docker ps -a --format '{{.Names}}' | grep -q '^dc-saas-'; then
    echo "[saas-macos] Existing dc-saas containers detected: do not run a one-click upgrade/reset until image/config drift checks pass."
  fi
  echo "[saas-macos] No files, images, containers or runtime data were changed."
  exit 0
fi
# macOS lacks GNU flock. Own an atomic lock before ANY env or runtime mutation.
# Never erase a foreign/stale lock automatically; that could allow races.
lock_dir="${SAAS_AUTO_UPDATE_LOCK_FILE:-/tmp/dc-saas-auto-update.lock}.macos"
if ! mkdir "${lock_dir}" 2>/dev/null; then
  echo "[saas-macos] ERROR: another Mac SaaS operation holds ${lock_dir}; refusing concurrent deployment." >&2
  exit 1
fi
printf '%s\n' "$$" > "${lock_dir}/pid"
cleanup_lock() { rm -f -- "${lock_dir}/pid"; rmdir -- "${lock_dir}"; }
trap cleanup_lock EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ ! -f "$ENV_FILE" ]]; then
  cp "${SCRIPT_DIR}/.env.example" "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  echo "[saas-macos] created ${ENV_FILE} from .env.example"
fi



"${SCRIPT_DIR}/scripts/apply-release-image-lock.sh" "$ENV_FILE" "${RELEASE_IMAGE_LOCK:-${SCRIPT_DIR}/release/saas-crypto-images.env}"
"${SCRIPT_DIR}/scripts/upsert-env-value.sh" "$ENV_FILE" DEPLOY_ROOT "${MACOS_DEPLOY_ROOT:-${HOME}/.opentradingcore/dc-saas-runtime}"
"${SCRIPT_DIR}/scripts/upsert-env-value.sh" "$ENV_FILE" BUILD_ROOT "${MACOS_BUILD_ROOT:-${HOME}/.opentradingcore/dc-saas-build}"
mkdir -p "${MACOS_DEPLOY_ROOT:-${HOME}/.opentradingcore/dc-saas-runtime}" "${MACOS_BUILD_ROOT:-${HOME}/.opentradingcore/dc-saas-build}"

memory_bytes="$(sysctl -n hw.memsize)"
memory_mb=$((memory_bytes / 1024 / 1024))
min_memory_mb="${SAAS_MIN_TOTAL_MEMORY_MB:-7680}"
(( memory_mb >= min_memory_mb )) || { echo "[saas-macos] ERROR: ${memory_mb} MiB RAM installed; ${min_memory_mb} MiB required." >&2; exit 1; }

if ! docker ps -a --format '{{.Names}}' | grep -q '^dc-saas-'; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  ports=(
    "${MYSQL_PORT:-33306}" "${CLICKHOUSE_HTTP_PORT:-38123}" "${CLICKHOUSE_NATIVE_PORT:-39000}"
    "${ZOOKEEPER_PORT:-32181}" "${GW_TCP_PORT:-33000}" "${GW_WEBSOCKET_PORT:-33001}" "${GW_HTTP_PORT:-33002}"
    "${LOGINSVR_HTTP_PORT:-33990}" "${LOGINSVR_GW_PORT:-33034}" "${MDSVR_GW_PORT:-33028}" "${MDSVR_B_GW_PORT:-33043}" "${MDSVR_C_GW_PORT:-33045}"
    "${APSSVR_GW_PORT:-33035}" "${ORDERSVR_GW_PORT:-33036}" "${ORDERSVR_B_GW_PORT:-33041}" "${ORDERSVR_C_GW_PORT:-33044}"
    "${PROJECTIONSVR_GW_PORT:-33042}" "${TRADESVR_GW_PORT:-33037}" "${TRADESVR_B_GW_PORT:-33046}"
    "${LIQSVR_GW_PORT:-33038}" "${MANAGERSVR_GW_PORT:-33039}" "${ADMINSVR_GW_PORT:-33040}"
    "${WEB_LISTEN_PORT:-18088}" 18090 18092 18094 18096
    "${ORDERSVR_A_REPLICATION_PORT:-19121}" "${ORDERSVR_B_REPLICATION_PORT:-19122}" "${ORDERSVR_C_REPLICATION_PORT:-19123}"
    "${TRADESVR_A_REPLICATION_PORT:-19221}" "${TRADESVR_B_REPLICATION_PORT:-19222}"
  )
  for port in "${ports[@]}"; do
    if "${SCRIPT_DIR}/scripts/port-is-listening.sh" "$port"; then
      echo "[saas-macos] ERROR: port ${port} is already in use." >&2
      exit 1
    fi
  done
fi

echo "[saas-macos] preflight passed; using immutable release lock and Docker $(docker context show)."


SAAS_ALLOW_UNPRIVILEGED_HOST=true \
SAAS_DEPLOY_LOCK_HELD=true \
SAAS_SKIP_LINUX_HOST_PREFLIGHT=true \
ENV_FILE="$ENV_FILE" \
"${SCRIPT_DIR}/deploy-saas.sh" "$@"
