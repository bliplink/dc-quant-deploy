#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="${DEPLOY_ROOT:-/data/strategy}"
SEED="${1:-${SCRIPT_DIR}/recovery/live-strategy-seed-current.json}"
shift || true

if [[ ! -f "${SEED}" ]]; then
  SEED="${DEPLOY_ROOT}/data/indsvr/backup/live-strategy-seed-current.json"
fi

python3 "${SCRIPT_DIR}/recovery/restore_live_strategies.py" \
  --env-file "${SCRIPT_DIR}/.env.prod" \
  --seed "${SEED}" \
  "$@"
