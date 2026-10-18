#!/usr/bin/env bash
# Verify real self-service onboarding: SUBMIT -> AUTO_APPROVAL -> liquidity job -> Robot/Tape.
# Supply E2E_AUTO_TENANT_ADMIN_PASSWORD out of band; this script never prints credentials.
set -euo pipefail
: "${E2E_AUTO_TENANT_ADMIN_PASSWORD:?set E2E_AUTO_TENANT_ADMIN_PASSWORD securely before running}"
[[ ${#E2E_AUTO_TENANT_ADMIN_PASSWORD} -ge 8 ]] || { echo 'Admin password too short' >&2; exit 2; }
BASE="${E2E_BASE_URL:-http://127.0.0.1:18088/httpapi/}"
SUFFIX="${E2E_SUFFIX:-$(date +%H%M%S)}"
LOCATION="${E2E_LOCATION:-A${SUFFIX: -5}}"
EMAIL="auto-${SUFFIX}@acceptance.invalid"
umask 077
ROOT="${E2E_OUTPUT_DIR:-$(mktemp -d /tmp/otc-tenant-smoke.XXXXXX)}"
mkdir -p "$ROOT"
REQ="$ROOT/auto-tenant-application-${LOCATION}.json"
OUT="$ROOT/auto-tenant-result-${LOCATION}.json"
trap 'rm -f -- "$REQ"' EXIT
python3 - "$LOCATION" "$EMAIL" "$SUFFIX" "$REQ" <<'PY'
import json,os,sys
location,email,suffix,path=sys.argv[1:]
obj={'serverName':'ManagerSvr','method':'tenantApplication','content':{'action':'SUBMIT','cid':'AUTO_'+suffix,'request_id':'AUTO_'+suffix,'tenant_code':location,'organization_name':'Auto-approval E2E '+location,'contact_name':'Automated Acceptance','contact_email':email,'admin_password':os.environ['E2E_AUTO_TENANT_ADMIN_PASSWORD'],'expected_users':20,'requested_symbols':['BTCUSDT'],'requested_trial_days':30}}
with open(path,'w') as f: json.dump(obj,f)
os.chmod(path,0o600)
PY
curl --noproxy '*' --fail --silent --show-error --max-time 35 -H 'Content-Type: application/json' --data-binary "@$REQ" "$BASE" > "$OUT"
rm -f -- "$REQ"
APP_ID="$(python3 - "$OUT" <<'PY'
import json,re,sys
r=json.load(open(sys.argv[1])); assert r.get('code')==0, 'tenant submission failed'
appid=str((r.get('data') or {}).get('application_id',''))
assert re.fullmatch(r'[a-f0-9]{32}',appid), 'missing or invalid application_id'
print(appid)
PY
)"
# Auto-approval is inside submit; no platform manager login is required.
# All SQL literals below originate from our validated fixed-format location code.
[[ "$LOCATION" =~ ^[A-Z][A-Z0-9]{5}$ ]] || { echo "Invalid location for smoke test" >&2; exit 2; }
query(){
  printf '%s\n' "$1" | docker exec -i dc-saas-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc' 2>/dev/null
}
STATE=''
for i in $(seq 1 30); do
  STATE="$(query "SELECT CONCAT(status,':',COALESCE(approved_location,'')) FROM dc_tenant_application WHERE application_id='${APP_ID}' LIMIT 1" || true)"
  [[ "$STATE" == APPROVED:* ]] && break
  sleep 1
done
[[ "$STATE" == APPROVED:* ]] || { echo "FAIL: application $LOCATION not auto-approved (state $STATE)" >&2; exit 3; }
APPROVED="${STATE#APPROVED:}"
[[ "$APPROVED" =~ ^[A-Z][A-Z0-9]{5}$ ]] || { echo 'Invalid approved location' >&2; exit 3; }
TENANT="$(query "SELECT CONCAT(status,':',trade_enabled,':',registration_enabled) FROM dc_tenant WHERE location='${APPROVED}'")"
[[ "$TENANT" == TRIAL:1:1 ]] || { echo "FAIL: tenant not enabled ($TENANT)" >&2; exit 3; }
JOB=''
for i in $(seq 1 72); do
  JOB="$(query "SELECT CONCAT(status,':',step,':',tape_enabled,':',tape_funding_confirmed) FROM dc_tenant_liquidity_bootstrap WHERE location='${APPROVED}' LIMIT 1" || true)"
  [[ "$JOB" == COMPLETE:DONE:1:1 ]] && break
  sleep 5
done
[[ "$JOB" == COMPLETE:DONE:1:1 ]] || { echo "FAIL: Robot/Tape initialization did not complete ($JOB)" >&2; exit 4; }
LIVE="$(query "SELECT COUNT(*) FROM dc_tenant_robot WHERE location='${APPROVED}' AND enabled=1 AND runtime_status='RUNNING' AND open_order_count>=2")"
[[ "$LIVE" -ge 1 ]] || { echo 'FAIL: no live two-sided Robot quotes' >&2; exit 5; }
echo "PASS location=$APPROVED auto_approval=APPROVED maker_robot=RUNNING quotes=two_sided tape=enabled_and_funded"
# Tape actual executions must be checked separately against Trade/Projection events.
