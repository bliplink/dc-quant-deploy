#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/docker-entrypoint-initdb.d"

run_sql_dir() {
  local dir="$1"
  shopt -s nullglob
  for file in "${dir}"/*.sql; do
    echo "Applying ${file}"
    clickhouse-client --multiquery < "${file}"
  done
}

clickhouse-client --query "CREATE DATABASE IF NOT EXISTS dc"
run_sql_dir "${ROOT_DIR}/10-schema"
run_sql_dir "${ROOT_DIR}/20-view"

echo "Optional SQL under ${ROOT_DIR}/90-optional-seed is not applied automatically."
