#!/usr/bin/env bash
# Non-mutating Broker candidate rollout smoke check.
# This is NOT an acceptance test for live Broker PRICE_PUBLISH, custom price
# activation, customer trading, HA failover, or performance.
set -euo pipefail
TENANT="${CANARY_TENANT:-GW7XMI}"
ENV_FILE="${ENV_FILE:-/Users/kong/.opentradingcore/ha-fresh-clean-demo-20261016.env}"
failures=0
ok(){ printf 'PASS %s\n' "$*"; }
fail(){ printf 'FAIL %s\n' "$*"; failures=$((failures+1)); }
for service in adminsvr managersvr apssvr mdsvr mdsvr-b mdsvr-c; do
  container="dc-saas-$service"
  if [ "$(docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null || true)" != running ]; then
    fail "$container process not running";continue
  fi
  # Docker Up is not enough: a Spring Bean naming conflict can leave a Java
  # process alive after the actual web application failed to initialize.
  started="$(docker inspect "$container" --format '{{.State.StartedAt}}')"
  if docker logs --since "$started" "$container" 2>&1 | grep -F 'Started application in ' >/dev/null; then
    ok "$container spring context initialized"
  else
    fail "$container spring context did not initialize"
  fi
done
for url in https://opentradingcore.com https://trade.opentradingcore.com;do
  status="$(curl -ksSL --max-time 10 -o /dev/null -w '%{http_code}' "$url" || true)"
  if [ "$status" = 200 ]; then ok "$url HTTP200";else fail "$url HTTP $status";fi
done
select_sql="SELECT CONCAT(price_source,'/',liquidity_source,'/',price_switch_state,'/',source_switch_state) FROM dc_tenant WHERE location='$TENANT';SELECT CONCAT(runtime_status,'/',open_order_count) FROM dc_tenant_robot WHERE location='$TENANT';SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc' AND table_name='dc_tenant' AND column_name IN ('price_source','liquidity_source','source_config_version','source_switch_state','pending_price_source','price_switch_state');"
db_rows="$(printf '%s\n' "$select_sql" | docker exec -i dc-saas-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc' 2>/dev/null || true)"
source_mode="$(printf '%s\n' "$db_rows" | sed -n '1p')"
robot_line="$(printf '%s\n' "$db_rows" | sed -n '2p')"
col_count="$(printf '%s\n' "$db_rows" | sed -n '3p')"
if [ "$source_mode" = 'SYSTEM/SYSTEM/ACTIVE/ACTIVE' ];then ok "$TENANT existing source remains SYSTEM/SYSTEM";else fail "$TENANT invalid source state $source_mode";fi
if [[ "$robot_line" =~ ^RUNNING/([0-9]+)$ ]] && [ "${BASH_REMATCH[1]}" -gt 0 ];then ok "$TENANT Robot RUNNING, live quotes ${BASH_REMATCH[1]}";else fail "$TENANT Robot unhealthy: $robot_line";fi
if [ "$col_count" = 6 ];then ok 'Broker source schema 6/6';else fail 'Broker source schema incomplete';fi
if [ "$failures" -eq 0 ]; then
  # Never interpolate API keys or user passwords into this test.
  python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys,urllib.request,json
path=Path(sys.argv[1]);assert path.exists()
port=next((s.partition('=')[2].strip().strip('"').strip("'") for s in path.read_text().splitlines() if s.startswith('WEB_LISTEN_PORT=')),None)
assert port is not None,"WEB_LISTEN_PORT missing"
for method,action in [('tenantBrokerLiquiditySwitch','BEGIN'),('tenantBrokerPriceSource','PREPARE')]:
    payload={'serverName':'AdminSvr','method':method,'content':{'action':action,'location':'GW7XMI','source_config_version':1,'cid':'CANARY_NO_AUTH'}}
    request=urllib.request.Request('http://127.0.0.1:'+port+'/httpapi/',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response:reply=json.load(response)
    if reply.get('code')!=10004 or reply.get('msg')!='AUTHENTICATED_SESSION_REQUIRED':
       raise SystemExit('FAIL unauthenticated '+method+' code='+str(reply.get('code')))
    print('PASS unauthenticated '+method+' denied')
PY
  echo 'CANARY_STAGING_HEALTH=PASS (NOT FULL BROKER API E2E)'
else
  echo "CANARY_STAGING_HEALTH=FAIL ($failures checks failed)"
  exit 1
fi
