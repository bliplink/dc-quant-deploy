#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${CLICKHOUSE_INIT_ROOT:-/docker-entrypoint-initdb.d}"
CLICKHOUSE_HOST="${CLICKHOUSE_HOST:-127.0.0.1}"
CLICKHOUSE_PORT="${CLICKHOUSE_PORT:-8123}"
CLICKHOUSE_USER="${CLICKHOUSE_USER:-default}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-}"
CLICKHOUSE_DB="${CLICKHOUSE_DB:-dc}"

client_cmd() {
  local args
  args=(clickhouse-client --host "${CLICKHOUSE_HOST}" --port "${CLICKHOUSE_PORT}" --user "${CLICKHOUSE_USER}")
  if [[ -n "${CLICKHOUSE_PASSWORD}" ]]; then
    args+=(--password "${CLICKHOUSE_PASSWORD}")
  fi
  if [[ $# -gt 0 ]]; then
    args+=("$@")
  fi
  "${args[@]}"
}

run_sql_dir() {
  local dir="$1"
  shopt -s nullglob
  for file in "${dir}"/*.sql; do
    echo "Applying ${file}"
    client_cmd --database "${CLICKHOUSE_DB}" --multiquery < "${file}"
  done
}

client_cmd --query "CREATE DATABASE IF NOT EXISTS ${CLICKHOUSE_DB}"
run_sql_dir "${ROOT_DIR}/10-schema"
run_sql_dir "${ROOT_DIR}/20-view"

echo "Optional SQL under ${ROOT_DIR}/90-optional-seed is not applied automatically."
