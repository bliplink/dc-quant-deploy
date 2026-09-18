#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Stable operator entry point. Keep all deployment behaviour in deploy-saas.sh
# so install, redeploy and auto-update share one implementation.
exec "${SCRIPT_DIR}/deploy-saas.sh" "$@"
