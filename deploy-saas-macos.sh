#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -s)" == "Darwin" ]] || { echo "[saas-macos] ERROR: this entrypoint is for macOS only." >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "[saas-macos] ERROR: Docker Desktop is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[saas-macos] ERROR: docker compose is required." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "[saas-macos] ERROR: Docker Desktop is not running." >&2; exit 1; }

ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
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
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[saas-macos] ERROR: port ${port} is already in use." >&2
      exit 1
    fi
  done
fi

echo "[saas-macos] preflight passed; using immutable release lock and Docker Desktop."
SAAS_ALLOW_UNPRIVILEGED_HOST=true \
SAAS_DEPLOY_LOCK_HELD=true \
SAAS_SKIP_LINUX_HOST_PREFLIGHT=true \
ENV_FILE="$ENV_FILE" \
exec "${SCRIPT_DIR}/deploy-saas.sh" "$@"
