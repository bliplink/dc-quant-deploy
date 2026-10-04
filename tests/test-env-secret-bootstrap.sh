#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy-saas.sh"
for key in MYSQL_PASSWORD MYSQL_ROOT_PASSWORD CLICKHOUSE_PASSWORD LOGIN_DEFAULT_PASSWORD PLATFORM_ADMIN_PASSWORD DC_HEDGE_CREDENTIAL_MASTER_KEY; do
  grep -Fq "ensure_generated_env_secret ${key}" "$DEPLOY" || {
    echo "missing placeholder-secret bootstrap for ${key}" >&2
    exit 1
  }
done
# The macOS one-click path intentionally starts from .env.example and relies on
# deploy-saas.sh to replace placeholders before any service starts.
grep -Fq 'cp "${SCRIPT_DIR}/.env.example" "$ENV_FILE"' "${ROOT}/deploy-saas-macos.sh"
echo '[env-secret-bootstrap] PASS: copied templates cannot retain core placeholder secrets'
