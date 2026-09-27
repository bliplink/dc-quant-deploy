#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
[[ -r "${ENV_FILE}" ]] || { echo "missing ${ENV_FILE}" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
RUN_ID="${LOAD_RUN_ID:-nd$(date +%H%M%S)}"
export ENV_FILE
export LOAD_LOCATION="${LOAD_LOCATION:-A6D0BE}"
export LOAD_MAKER="${LOAD_MAKER:-stressmaker_${RUN_ID}}"
export LOAD_TAKER="${LOAD_TAKER:-stresstaker_${RUN_ID}}"
export LOAD_ORDERS="${LOAD_ORDERS:-1000}"
export LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-16}"
export LOAD_RELOAD_BEFORE=false
export LOAD_PAUSE_BACKGROUND=false
export LOAD_VERIFY_RESTART=false
export LOAD_RUN_ID="${RUN_ID}"
export LOAD_ARTIFACT_DIR="${LOAD_ARTIFACT_DIR:-${DEPLOY_DIR}/.tmp-e2e-artifacts/stress-${RUN_ID}}"
export LOAD_E2E_PASSWORD="${LOAD_E2E_PASSWORD:-${E2E_PASSWORD:-${LOGIN_DEFAULT_PASSWORD:-}}}"
exec /bin/bash "${SCRIPT_DIR}/run-core-trading-stress-host.sh"
