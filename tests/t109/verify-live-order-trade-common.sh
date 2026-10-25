#!/bin/sh
# Strict, read-only real live Demo check. Exit 0 ONLY when every actual
# Order/Trade JVM runs a freshly certified Common business node with no
# startup fatal, AND a separate transaction/failover gate is supplied.
# Container 'Up' never counts as business READY.
set -eu
fatal=0
for item in \
 'dc-saas-ordersvr|local/otc-t108-ordersvr:common-zk-765d4b7' \
 'dc-saas-ordersvr-b|local/otc-t108-ordersvr:common-zk-765d4b7' \
 'dc-saas-ordersvr-c|local/otc-t108-ordersvr:common-zk-765d4b7' \
 'dc-saas-tradesvr|local/otc-t108-tradesvr:common-zk-5b110c8' \
 'dc-saas-tradesvr-b|local/otc-t108-tradesvr:common-zk-5b110c8'
do
  n=${item%%|*}
  expected=${item#*|}
  if ! docker inspect "$n" >/dev/null 2>&1;then
    echo "$n: MISSING — NO-GO";fatal=1;continue
  fi
  image=$(docker inspect "$n" --format '{{.Config.Image}}')
  state=$(docker inspect "$n" --format '{{.State.Status}}')
  restarts=$(docker inspect "$n" --format '{{.RestartCount}}')
  cause=$(docker logs --tail 350 "$n" 2>&1 | grep -E 'FATAL_(ORDER|TRADE)_COMMON_CLUSTER_STARTUP' |tail -1 || true)
  if [ "$image" != "$expected" ] || [ "$state" != running ] || [ -n "$cause" ];then
    echo "$n: NO-GO (image=$image, state=$state, restarts=$restarts)"
    [ -z "$cause" ] || echo "$n: $(printf '%s' "$cause" |cut -c1-210)"
    fatal=1
  else
    echo "$n: PROCESS_RUNNING (not proof of READY)"
  fi
done
if [ "$fatal" -ne 0 ];then
  echo 'T109_REAL_BUSINESS_STARTUP=NO-GO; fail-closed, no real trading or A-B-A evidence'
  exit 2
fi
echo 'T109_PROCESS_ONLY=PASS; functional trade and automatic HA still require separate PASS'
exit 3
