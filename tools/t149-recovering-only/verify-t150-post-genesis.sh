#!/usr/bin/env bash
# T150 isolated-candidate POST-GENESIS read-only acceptance.
# No READY grant, no fake Genesis, no mutation of the protected T84/demo environment.
set -euo pipefail
root="$HOME/.opentradingcore/t149-order-trade-deploy-20261026"
if [ "$#" -ge 1 ]; then root="$1"; fi
[ -d "$root/config" ] || { echo "T150_FAIL missing T149 config root" >&2; exit 1; }
for zk in zk1 zk2 zk3; do
  c="otc-t149-ha-intake-$zk-1"
  [ "$(docker inspect --format '{{.State.Running}}' "$c" 2>/dev/null || true)" = true ] ||
    { echo "T150_FAIL $zk is not running" >&2; exit 1; }
done
echo "T150_REAL_ZK_THREE_RUNNING_PASS"
prop() {
  awk -v k="$2" 'index($0,k"=")==1 { print substr($0,length(k)+2); exit }' "$1"
}
voter() {
  local unit="$1" svc="$2" shard="$3" primary="$4" replica="$5" self="$6"
  local c="otc-t149-ha-intake-$unit-1" out
  [ "$(docker inspect --format '{{.State.Running}}' "$c" 2>/dev/null || true)" = true ] ||
    { echo "T150_FAIL service not running $unit" >&2; return 1; }
  if ! out=$(docker exec "$c" sh -c "cd /srv/dc/dc/$svc && java -cp '/tmp:classes:lib/*' T150RealEmptyBusinessGenesis --verify $svc $shard $primary $replica $self" 2>&1); then
    echo "T150_FAIL original Genesis certificate $unit/$shard" >&2
    printf '%s\n' "$out" | tail -8 >&2
    return 1
  fi
  printf '%s\n' "$out" | grep -q "^T150_ORIGINAL_BUSINESS_GENESIS_INDEPENDENT_RSA_QUORUM_PASS service=$svc partition=$shard .*businessReady=false$" ||
    { echo "T150_FAIL missing exact Common certificate proof $unit/$shard" >&2; return 1; }
  echo "T150_GENESIS_REOPEN_PASS $unit $shard"
}
deny() {
  local unit="$1" svc="$2" shard="$3" prefix="$4"
  local c="otc-t149-ha-intake-$unit-1" cfg="$root/config/$unit/application.properties"
  [ -f "$cfg" ] || { echo "T150_FAIL missing $unit config" >&2; return 1; }
  local node port manifest lease out
  node=$(prop "$cfg" "$prefix.common.control.nodeId")
  port=$(prop "$cfg" "$prefix.common.nodeRuntime.bindPort")
  manifest=$(prop "$cfg" "$prefix.common.control.manifestPath")
  lease=$(prop "$cfg" "$prefix.common.control.leasePath")
  [ -n "$node" ] && [ -n "$port" ] && [ -n "$manifest" ] && [ -n "$lease" ] ||
    { echo "T150_FAIL missing Common-only identity $unit" >&2; return 1; }
  if ! out=$(docker exec "$c" sh -c "cd /srv/dc/dc/$svc && java -cp '/tmp:classes:lib/*' T149RecoveryOnlyProbe $svc $node $shard $port $manifest $lease zk1:2181,zk2:2181,zk3:2181" 2>&1); then
    echo "T150_FAIL Common Netty/ZK post-genesis rejection $unit" >&2
    printf '%s\n' "$out" | tail -8 >&2
    return 1
  fi
  printf '%s\n' "$out" | grep -q '^T149_REAL_NODE_ZK_EPHEMERAL_LEASE_TCP_DENY_PASS .*ready=false .*businessWal=DENIED unsignedCommit=DENIED sessionOwner=VALID$' ||
    { echo "T150_FAIL missing strict rejected-WAL marker $unit" >&2; return 1; }
  echo "T150_POST_GENESIS_NOT_READY_PASS $unit $shard"
}
voter ordersvr-a OrderSvr P090 OrderSvrA OrderSvrB OrderSvrA
voter ordersvr-b OrderSvr P090 OrderSvrA OrderSvrB OrderSvrB
voter ordersvr-b OrderSvr P091 OrderSvrC OrderSvrB OrderSvrB
voter ordersvr-c OrderSvr P091 OrderSvrC OrderSvrB OrderSvrC
voter tradesvr-a TradeSvr P090 TradeSvrA TradeSvrB TradeSvrA
voter tradesvr-b TradeSvr P090 TradeSvrA TradeSvrB TradeSvrB
deny ordersvr-a OrderSvr P090 order
deny ordersvr-b OrderSvr P090 order
deny ordersvr-c OrderSvr P091 order
deny tradesvr-a TradeSvr P090 trade
deny tradesvr-b TradeSvr P090 trade
echo "T150_POST_GENESIS_6_RSA_REOPEN_5_FENCED_PASS"
echo "T150_NO_GO: one-Mac volumes are NOT independent physical hosts. No certified business replay, READY or HA promotion."
