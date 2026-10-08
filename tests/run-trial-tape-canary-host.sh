#!/usr/bin/env bash
# Opt-in, single-tenant conversion of an existing completed maker-only trial.
# Never repeats maker cashIn, never touches the other tenants or RobotSvr.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT}/.env.prod}"
LOCATION="${TAPE_CANARY_LOCATION:-}"
[[ "${LOCATION}" =~ ^[A-Z0-9]{6}$ ]] || { echo "TAPE_CANARY_LOCATION must be a 6-character ID" >&2; exit 2; }
[[ "${TAPE_CANARY_CONFIRM:-}" == "${LOCATION}" && "${TAPE_CANARY_APPLY:-}" == "YES" ]] ||
  { echo "Set TAPE_CANARY_APPLY=YES and TAPE_CANARY_CONFIRM=<location> to opt in" >&2; exit 2; }
[[ -r "${ENV_FILE}" ]] || { echo "ENV_FILE not readable" >&2; exit 2; }
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
[[ "${TRIAL_LIQUIDITY_TAPE_ENABLED:-false}" == true ]] ||
  { echo "Enable TRIAL_LIQUIDITY_TAPE_ENABLED in the deployed AdminSvr first" >&2; exit 2; }
[[ "${TRIAL_LIQUIDITY_TAPE_CANARY_LOCATION:-}" == "${LOCATION}" ]] ||
  { echo "AdminSvr canary does not match requested location" >&2; exit 2; }
mysql_read() {
  docker exec -i -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -N dc -e "$1"
}
# Do not rewind any uncertain cashIn or already-tape-enabled job.
read -r status step maker_confirmed tape_enabled tape_confirmed robot_count <<<"$(mysql_read "
  SELECT b.status,b.step,b.funding_confirmed,b.tape_enabled,b.tape_funding_confirmed,
    (SELECT COUNT(*) FROM dc_tenant_robot r WHERE r.location=b.location AND r.enabled=1)
  FROM dc_tenant_liquidity_bootstrap b JOIN dc_tenant t ON t.location=b.location
  WHERE b.location='${LOCATION}' AND t.status='TRIAL' AND t.trade_enabled=1
    AND t.source_application_id=b.application_id
    AND (t.trial_end_time IS NULL OR t.trial_end_time>=NOW());")"
[[ "${status:-}" == COMPLETE && "${step:-}" == DONE && "${maker_confirmed:-}" == 1 &&
   "${tape_enabled:-}" == 0 && "${tape_confirmed:-}" == 0 && "${robot_count:-}" == 1 ]] ||
   { echo "Canary preconditions failed: state=${status:-missing}/${step:-missing} maker=${maker_confirmed:-0} tape=${tape_enabled:-0}/${tape_confirmed:-0} robot=${robot_count:-0}" >&2; exit 2; }
result="$(mysql_read "
  UPDATE dc_tenant_liquidity_bootstrap SET status='PENDING',step='REVOKE_CASH',
    attempts=0,next_attempt_time=NULL,lease_owner=NULL,lease_until=NULL,
    last_error_code=NULL,last_error_message=NULL,complete_time=NULL,
    update_time=NOW(3)
  WHERE location='${LOCATION}' AND status='COMPLETE' AND step='DONE'
    AND funding_confirmed=1 AND tape_enabled=0 AND tape_funding_confirmed=0;
  SELECT ROW_COUNT();")"
[[ "${result}" == 1 ]] || { echo "Canary compare-and-swap failed" >&2; exit 1; }
echo "[trial-tape-canary] queued location=${LOCATION} (maker funding remains confirmed; no repeat cashIn)"
