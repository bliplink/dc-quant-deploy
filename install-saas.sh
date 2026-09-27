#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Stable operator entry point. deploy-saas.sh owns deployment/redeploy behavior;
# install-saas.sh adds the persistent default E2E/demo bootstrap only after the
# full stack has passed its normal validation. Auto-update calls deploy-saas.sh
# directly, so routine image upgrades do not recreate or re-fund the demo tenant.
for arg in "$@"; do
  if [[ "${arg}" == "-h" || "${arg}" == "--help" ]]; then
    exec "${SCRIPT_DIR}/deploy-saas.sh" "$@"
  fi
done

"${SCRIPT_DIR}/deploy-saas.sh" "$@"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}" "${SCRIPT_DIR}/bootstrap-default-e2e.sh"
