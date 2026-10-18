#!/usr/bin/env bash
# Broker API v1 release gate. READ-ONLY: no tenant registration, database write,
# container restart or HA fault injection. This runs before the create-tenant E2E.
set -euo pipefail
failures=0
pass(){ printf 'PASS: %s\n' "$1"; }
fail(){ printf 'FAIL: %s\n' "$1"; failures=$((failures + 1)); }
check_class(){
  local container="$1" class_file="$2" purpose="$3"
  if docker exec "$container" sh -c 'test -f "$1"' -- "$class_file" >/dev/null 2>&1; then
    pass "$purpose deployed ($container)"
  else
    fail "$purpose not deployed ($container)"
  fi
}
for name in dc-saas-adminsvr dc-saas-apssvr dc-saas-mdsvr dc-saas-managersvr dc-saas-tradesvr dc-saas-liqsvr dc-saas-robotsvr dc-saas-mysql;do
  if [ "$(docker inspect "$name" --format '{{.State.Status}}' 2>/dev/null || true)" = running ];then pass "$name running";else fail "$name not running";fi
done
# Never print root credentials, API keys, login responses or personal data.
col_count="$(printf '%s\n' "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='dc_tenant' AND column_name IN ('price_source','liquidity_source','source_config_version','source_switch_state','pending_price_source','price_switch_state');" | docker exec -i dc-saas-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc' 2>/dev/null || true)"
if [ "$col_count" = 6 ];then pass 'source schema 6/6 columns';else fail "Broker source schema columns not installed: ${col_count:-unavailable}/6";fi
check_class dc-saas-apssvr /srv/dc/dc/APSSvr/classes/com/app/dc/handler/PublishBrokerPriceHandler.class 'APS Broker price ingress'
check_class dc-saas-mdsvr /srv/dc/dc/MDSvr/classes/com/app/dc/service/index/BrokerTenantPriceInput.class 'MD Broker price receiver'
check_class dc-saas-adminsvr /srv/dc/dc/AdminSvr/classes/com/app/dc/handler/TenantBrokerLiquiditySwitchHandler.class 'Admin Broker liquidity handover'
check_class dc-saas-adminsvr /srv/dc/dc/AdminSvr/classes/com/app/dc/handler/TenantBrokerPriceSourceHandler.class 'Admin Broker price staging'
check_class dc-saas-managersvr /srv/dc/dc/ManagerSvr/classes/com/app/dc/service/RobotRuntimeService.class 'Robot scheduler'
# The classes above are packaging checks only. To claim Broker v1.0 ready,
# an operator must also attach verified tests for authenticated publisher lease,
# Trade/Liq stale-price gating, WS snapshot recovery, customer settlement and HA.
if [ "$failures" -eq 0 ]; then
  printf 'PARTIAL: packaging/schema prerequisites pass; real Broker E2E still mandatory.\n'
else
  printf 'BLOCKED: %d deployment prerequisite(s) failed; do NOT create final acceptance tenant yet.\n' "$failures"
fi
exit "$((failures > 0))"
