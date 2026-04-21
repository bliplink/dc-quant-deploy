#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a
fi

: "${CLICKHOUSE_IMAGE_TAG:?CLICKHOUSE_IMAGE_TAG is required}"
: "${CLICKHOUSE_DB_NAME:?CLICKHOUSE_DB_NAME is required}"
: "${CLICKHOUSE_HOST:?CLICKHOUSE_HOST is required}"
: "${CLICKHOUSE_HTTP_PORT:?CLICKHOUSE_HTTP_PORT is required}"
: "${CLICKHOUSE_NATIVE_PORT:?CLICKHOUSE_NATIVE_PORT is required}"

CLICKHOUSE_USERNAME="${CLICKHOUSE_USERNAME:-default}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-}"

docker run --rm --network host \
  -e CLICKHOUSE_INIT_ROOT=/work/init \
  -e CLICKHOUSE_HOST="${CLICKHOUSE_HOST}" \
  -e CLICKHOUSE_PORT="${CLICKHOUSE_NATIVE_PORT}" \
  -e CLICKHOUSE_DB="${CLICKHOUSE_DB_NAME}" \
  -e CLICKHOUSE_USER="${CLICKHOUSE_USERNAME}" \
  -e CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD}" \
  -v "${SCRIPT_DIR}/init:/work/init:ro" \
  "clickhouse/clickhouse-server:${CLICKHOUSE_IMAGE_TAG}" \
  bash /work/init/01-run-all.sh
