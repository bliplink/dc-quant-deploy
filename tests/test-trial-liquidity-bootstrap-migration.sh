#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATION="${ROOT}/mysql/migrations/20261004_trial_liquidity_bootstrap.sql"
DEPLOY="${ROOT}/deploy-saas.sh"
[[ -f "${MIGRATION}" ]]
grep -Fq 'CREATE TABLE IF NOT EXISTS dc_tenant_liquidity_bootstrap' "${MIGRATION}"
for column in application_id location status step funding_request_id maker_user_id api_key funding_amount funding_confirmed attempts next_attempt_time lease_owner lease_until last_error_code last_error_message create_time update_time complete_time; do
  grep -Eq "^[[:space:]]*${column}[[:space:]]" "${MIGRATION}"
done
grep -Fq 'idx_tenant_liquidity_bootstrap_pending (status, next_attempt_time, create_time)' "${MIGRATION}"
grep -Fq 'idx_tenant_liquidity_bootstrap_lease (status, lease_until)' "${MIGRATION}"
grep -Fq 'verify_mysql_runtime_schema' "${DEPLOY}"
python3 - "${DEPLOY}" <<'PY'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text()
assert s.index('apply_mysql_migrations\n') < s.index('verify_mysql_runtime_schema\nprovision_platform_admin')
assert s.count('verify_mysql_runtime_schema\nprovision_platform_admin') == 1
PY
echo '[trial-liquidity-bootstrap-migration-test] PASS'
