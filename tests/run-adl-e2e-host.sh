#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export FINAL_LIQ_E2E_SCENARIO=adl_multi
export FINAL_LIQ_E2E_LOCATION="${ADL_E2E_LOCATION:-${FINAL_LIQ_E2E_LOCATION:-ADL_E2E}}"
export FINAL_LIQ_E2E_OTHER_LOCATION="${ADL_E2E_OTHER_LOCATION:-${FINAL_LIQ_E2E_LOCATION}_FOREIGN}"
export FINAL_LIQ_E2E_USER="${ADL_E2E_LIQ_USER:-adl_liquidated}"
export FINAL_LIQ_E2E_OPEN_USER="${ADL_E2E_LOW_USER:-adl_low}"
export FINAL_LIQ_E2E_ADL_USER="${ADL_E2E_HIGH_USER:-adl_high}"
export FINAL_LIQ_E2E_FOREIGN_USER="${ADL_E2E_FOREIGN_USER:-adl_foreign}"
exec "${SCRIPT_DIR}/run-final-liquidation-e2e-authoritative-host.sh" "$@"
