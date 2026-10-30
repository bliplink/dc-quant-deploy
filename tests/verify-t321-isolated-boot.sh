#!/usr/bin/env bash
# T321 read-only isolation acceptance: no Gateway/order traffic, HA injection, or data mutation.
set -euo pipefail
ROOT="${OTC_T321_ROOT:-$HOME/.opentradingcore/t319-business-ready-20261030}"
NETWORK_ZK="otc-t84-source-integrated-otc-ha-zk1-1:2181"
SPECS=(
  "order-a|order/A|OrderSvr|45322"
  "order-b|order/B|OrderSvr|45323"
  "trade-a|trade/A|TradeSvr|45222"
  "trade-b|trade/B|TradeSvr|45223"
)
for spec in "${SPECS[@]}"; do
  IFS='|' read -r label path spring port <<< "$spec"
  name="otc-t321-$label"
  [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == true ]] || {
    echo "FAIL $name is not running" >&2; exit 1;
  }
  docker logs "$name" 2>&1 | grep -F "Started $spring in" >/dev/null || {
    echo "FAIL $name has no Spring startup marker" >&2; exit 2;
  }
  docker exec "$name" grep -Fx "REGISTER.Svr1.Host=$NETWORK_ZK" /srv/dc/control/ATSConfig.ini >/dev/null || {
    echo "FAIL $name inherited incorrect shared registry" >&2; exit 3;
  }
  wal_root="$ROOT/$path/data/t319-ready-v4"
  [[ -d "$wal_root" ]] || { echo "FAIL missing $wal_root" >&2; exit 4; }
  wal_count="$(find "$wal_root" -type f -name business.wal | wc -l | tr -d ' ')"
  [[ "$wal_count" == 256 ]] || {
    echo "FAIL $name expects exactly 256 isolated E2 WAL files, got $wal_count" >&2; exit 5;
  }
  if docker logs --since 60s "$name" 2>&1 | grep -Eq 'ZkTimeoutException|COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT| ERROR '; then
    echo "FAIL recent auth/registry/runtime error in $name" >&2; exit 6;
  fi
  docker exec otc-t321-trade-a bash -c "exec 3<>/dev/tcp/$name/$port" 2>/dev/null || {
    echo "FAIL Common Netty TCP not reachable at $name:$port" >&2; exit 7;
  }
  echo "T321_SPRING_REGISTRY_E2_WAL_TCP_PASS name=$name partitions=$wal_count port=$port"
done
echo 'T321_BOOT_ONLY_PASS businessTransactions=NOT_TESTED autoFailover=NOT_TESTED formalDemo=NO_GO'
