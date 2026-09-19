#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
RUN_ID="${ACCEPTANCE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

log() {
  printf '[saas-acceptance] %s\n' "$*"
}

die() {
  printf '[saas-acceptance] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || die "Run as root or with sudo."
[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

[[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]] ||
  die "Full acceptance requires ORDER_CLUSTER_ENABLED=true. Install with --full-cluster."
[[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]] ||
  die "Full acceptance requires MD_CLUSTER_ENABLED=true. Install with --full-cluster."
[[ "${MD_CLUSTER_C_ENABLED:-false}" == "true" ]] ||
  die "Full acceptance requires MD_CLUSTER_C_ENABLED=true. Install with --full-cluster."
[[ "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]] ||
  die "Full acceptance requires TRADE_CLUSTER_ENABLED=true. Install with --full-cluster."

E2E_PASSWORD="${E2E_PASSWORD:-${ACCEPTANCE_PASSWORD:-${LOGIN_DEFAULT_PASSWORD:-}}}"
[[ ${#E2E_PASSWORD} -ge 8 ]] || die "Acceptance password must contain at least 8 characters."
export E2E_PASSWORD

short_id="$(printf '%s' "${RUN_ID}" | tr -cd 'A-Za-z0-9' | tail -c 9)"
[[ -n "${short_id}" ]] || short_id="$(date -u +%H%M%S)"
short_id="${short_id,,}"
CORE_E2E_LOCATION="${CORE_E2E_LOCATION:-ACC$(date -u +%H%M%S)_E2E}"
CORE_E2E_BUYER="${CORE_E2E_BUYER:-buyer_${short_id}}"
CORE_E2E_SELLER="${CORE_E2E_SELLER:-seller_${short_id}}"
export CORE_E2E_LOCATION CORE_E2E_BUYER CORE_E2E_SELLER
export RUN_CORE_STRESS="${ACCEPTANCE_RUN_STRESS:-false}"

EVIDENCE_DIR="${ACCEPTANCE_EVIDENCE_DIR:-${DEPLOY_ROOT}/evidence/${RUN_ID}-full-acceptance}"
STATUS_FILE="${EVIDENCE_DIR}/steps.tsv"
SUMMARY_FILE="${EVIDENCE_DIR}/acceptance-summary.json"
install -d -m 0750 "${EVIDENCE_DIR}"
: > "${STATUS_FILE}"

record_status() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "${STATUS_FILE}"
}

write_summary() {
  local final_result="$1"
  python3 - "${STATUS_FILE}" "${SUMMARY_FILE}" "${final_result}" "${RUN_ID}" "${CORE_E2E_LOCATION}" <<'PY'
import json
import sys
from pathlib import Path

status_path, summary_path, final_result, run_id, location = sys.argv[1:]
steps = []
for raw in Path(status_path).read_text(encoding="utf-8").splitlines():
    if not raw:
        continue
    name, status, log_path = raw.split("\t", 2)
    steps.append({"name": name, "status": status, "log": log_path})
payload = {
    "runId": run_id,
    "location": location,
    "result": final_result,
    "steps": steps,
}
Path(summary_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("=" * 64)
print("DC SaaS Full Business Acceptance")
print("=" * 64)
for step in steps:
    print(f"{step['name']:<42} {step['status']}")
print("-" * 64)
print(f"{'FINAL RESULT':<42} {final_result}")
print(f"Evidence: {summary_path}")
print("=" * 64)
PY
}

run_step() {
  local name="$1"
  shift
  local log_file="${EVIDENCE_DIR}/${name}.log"
  log "START ${name}"
  if "$@" > >(tee "${log_file}") 2>&1; then
    record_status "${name}" PASS "${log_file}"
    log "PASS ${name}"
  else
    local rc=$?
    record_status "${name}" FAIL "${log_file}"
    write_summary FAIL
    exit "${rc}"
  fi
}

run_step 01-foundation-health \
  "${SCRIPT_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"

run_step 02-tenant-control-plane-web \
  env ENV_FILE="${ENV_FILE}" \
      E2E_SUFFIX="${short_id}" \
      E2E_ARTIFACT_DIR="${EVIDENCE_DIR}/tenant-web" \
      "${SCRIPT_DIR}/tests/run-tenant-lifecycle-web-e2e-host.sh"

run_step 03-registration-trading-risk \
  env ENV_FILE="${ENV_FILE}" \
      E2E_PASSWORD="${E2E_PASSWORD}" \
      CORE_E2E_LOCATION="${CORE_E2E_LOCATION}" \
      CORE_E2E_BUYER="${CORE_E2E_BUYER}" \
      CORE_E2E_SELLER="${CORE_E2E_SELLER}" \
      RUN_CORE_STRESS="${RUN_CORE_STRESS}" \
      "${SCRIPT_DIR}/tests/run-core-trading-acceptance.sh"

run_step 04-robot-liquidity \
  env ENV_FILE="${ENV_FILE}" \
      ROBOT_E2E_RUN_ID="${short_id}" \
      ROBOT_E2E_PASSWORD="${E2E_PASSWORD}" \
      "${SCRIPT_DIR}/tests/run-robot-liquidity-e2e-host.sh"

run_step 05-trade-role-reversal \
  env ENV_FILE="${ENV_FILE}" \
      TRADE_CLUSTER_EVIDENCE_ROOT="${EVIDENCE_DIR}" \
      "${SCRIPT_DIR}/tests/run-trade-cluster-role-reversal-host.sh"

run_step 06-final-health \
  "${SCRIPT_DIR}/validate-saas.sh" --env-file "${ENV_FILE}"

write_summary PASS
