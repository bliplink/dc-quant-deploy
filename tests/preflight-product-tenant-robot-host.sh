#!/usr/bin/env bash
# Read-only gate before promoting a rebuilt Demo to product testing.
# Checks durable platform/Robot identities and worker switches without exposing credentials.
set -euo pipefail
mysql_count() {
  printf '%s\n' "$1" | docker exec -i dc-saas-mysql \
    sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc' 2>/dev/null
}
platform_count="$(mysql_count "SELECT COUNT(*) FROM dc_users WHERE location='PLATFORM' AND enable=1")"
robot_key_count="$(mysql_count "SELECT COUNT(*) FROM dc_users_api WHERE location='PLATFORM' AND type='ROBOT_RUNTIME' AND enable=1")"
worker_enabled="$(docker inspect dc-saas-adminsvr --format '{{json .Config.Env}}' | python3 -c 'import json,sys;print("true" if "TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true" in json.load(sys.stdin) else "false")')"
tape_enabled="$(docker inspect dc-saas-adminsvr --format '{{json .Config.Env}}' | python3 -c 'import json,sys;print("true" if "TRIAL_LIQUIDITY_TAPE_ENABLED=true" in json.load(sys.stdin) else "false")')"
printf 'platform_active=%s robot_runtime_keys=%s liquidity_worker_enabled=%s tape_enabled=%s\n' \
  "$platform_count" "$robot_key_count" "$worker_enabled" "$tape_enabled"
if [[ "$platform_count" -lt 1 || "$robot_key_count" -lt 1 ]]; then
  echo 'FAIL: bootstrap identities missing. Run the authenticated deployment provision_platform_admin / provision_robot_runtime_identity stages and refresh LoginSvr credentials cache.' >&2
  exit 2
fi
if [[ "$worker_enabled" != true || "$tape_enabled" != true ]]; then
  echo 'FAIL: AdminSvr automatic trial liquidity or Tape is disabled.' >&2
  exit 3
fi
echo 'PASS: durable platform/Robot bootstrap identities and worker switches are present.'
# This is NOT a live Robot login or quoting test. Run the tenant E2E next.
