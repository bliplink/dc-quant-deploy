#!/usr/bin/env bash
# Read-only T325 live acceptance: actual formal containers, existing Gateway/ZK,
# signed E2 WAL roots, Robot quote status. No new orders, no failover, no secrets.
set -euo pipefail
cd "$(dirname "$0")/.."
root="${DEPLOY_ROOT:-$HOME/.opentradingcore/dc-saas-runtime-clean-20261016}"
command -v docker >/dev/null
for item in 'ordersvr|OrderSvr|OrderSvrA|33036' 'ordersvr-b|OrderSvr|OrderSvrB|33041' 'tradesvr|TradeSvr|TradeSvrA|33037' 'tradesvr-b|TradeSvr|TradeSvrB|33046'; do
  IFS='|' read -r container svc node port <<<"$item"
  name="dc-saas-$container"
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name")" != "true" ]];then
    echo "T325_FAIL_NOT_RUNNING $name" >&2;exit 2
  fi
  image="$(docker inspect "$name" --format '{{.Config.Image}}')"
  case "$svc:$image" in
    OrderSvr:local/otc-t319-ordersvr:virgin-e2-replica|TradeSvr:local/otc-t319-tradesvr:virgin-e2-replica) ;;
    *) echo "T325_FAIL_UNVERIFIED_IMAGE $name" >&2;exit 3;;
  esac
  docker logs "$name" 2>&1 | grep -F "COMMON_GATEWAY_DISCOVERY_CERTIFIED service=$svc node=$node endpoint=127.0.0.1:$port exactOwnerSession=true" >/dev/null || {
    echo "T325_FAIL_REGISTRATION $name" >&2;exit 4;
  }
  docker logs "$name" 2>&1 | grep -F "Started $svc in" >/dev/null || { echo "T325_FAIL_SPRING $name" >&2;exit 5; }
  count="$(find "$root/data/t325-trading-e2/$svc/$node" -name business.wal -type f | wc -l | tr -d ' ')"
  [[ "$count" == 256 ]] || { echo "T325_FAIL_PARTITION_COUNT $name $count" >&2;exit 6;}
  echo "T325_FORMAL_SPRING_ZK_REGISTER_WAL_PASS name=$name port=$port partitions=$count"
done
zkout="$(docker exec dc-saas-zookeeper sh -c 'printf "ls /MDTService/OrderSvr\nls /MDTService/TradeSvr\nquit\n" | zkCli.sh -server 127.0.0.1:32181' 2>&1)"
grep -q 'OrderSvrA[0-9]\+.*OrderSvrB[0-9]\+' <<<"$zkout" || {
  echo "T325_FAIL_ORDER_ZK_SERVICE_DISCOVERY" >&2; exit 7;
}
grep -q 'TradeSvrA[0-9]\+.*TradeSvrB[0-9]\+' <<<"$zkout" || {
  echo "T325_FAIL_TRADE_ZK_SERVICE_DISCOVERY" >&2; exit 8;
}
echo "T325_ORIGINAL_GATEWAY_ZK_DISCOVERY_PASS order=2 trade=2"
echo "T325_BOOT_ONLY_PASS trades=NOT_VERIFIED tapeKline=NO_GO projectionCommonCertifiedReader=NOT_CONNECTED strictHA=NOT_TESTED"
