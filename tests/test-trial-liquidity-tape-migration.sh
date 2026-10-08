#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATION="${ROOT}/mysql/migrations/20261008_trial_liquidity_tape.sql"
[[ -f "${MIGRATION}" ]]
for column in tape_enabled tape_user_id tape_api_key tape_funding_request_id tape_funding_amount tape_funding_confirmed; do
  grep -Fq "column_name='${column}'" "${MIGRATION}"
  grep -Fq "ADD COLUMN ${column}" "${MIGRATION}"
  grep -q "${column}" "${ROOT}/deploy-saas.sh"
done
grep -Fq 'uq_tenant_liquidity_tape_funding' "${MIGRATION}"
grep -Fq 'TRIAL_LIQUIDITY_TAPE_ENABLED: ${TRIAL_LIQUIDITY_TAPE_ENABLED:-false}' "${ROOT}/compose.yaml"
grep -Fq 'TRIAL_LIQUIDITY_TAPE_CANARY_LOCATION:' "${ROOT}/compose.yaml"
grep -Fq 'TRIAL_LIQUIDITY_TAPE_CASH_AMOUNT:' "${ROOT}/compose.yaml"
grep -Fq 'TRIAL_LIQUIDITY_TAPE_ENABLED=false' "${ROOT}/.env.example"
echo '[trial-liquidity-tape-migration-test] PASS'
