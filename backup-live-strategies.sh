#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/data/strategy}"
OUTPUT="${1:-${DEPLOY_ROOT}/data/indsvr/backup/live-strategy-seed-current.json}"

python3 "${SCRIPT_DIR}/recovery/backup_live_strategies.py" \
  --env-file "${SCRIPT_DIR}/.env.prod" \
  --output "${OUTPUT}"
