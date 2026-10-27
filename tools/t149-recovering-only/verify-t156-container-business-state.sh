#!/usr/bin/env bash
# T156: read-only actual Order/Trade domain recovery classes INSIDE each
# T153 isolated ARM64 service container. Does not run a user-facing service
# or take the ZK lease of the existing RECOVERING Common business process.
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "Usage: bash verify-t156-container-business-state.sh <Order-T152-source> <Trade-T152-source>" >&2
  exit 2
fi
order="$1";trade="$2"
for x in "$order" "$trade"; do
  if [[ "$x" != /* ]] || [ ! -d "$x/target/dependency" ] || [ ! -d "$x/target/classes" ]; then
    echo "T156_DENIED: exact prebuilt absolute local Order/Trade source required" >&2
    exit 1
  fi
done
[ "$(git -C "$order" rev-parse HEAD)" = "4b1c7d8fce274208f4d6f74d7b70998775ad0a35" ] || {
  echo 'T156_DENIED: wrong original Order source';exit 1;
}
[ "$(git -C "$trade" rev-parse HEAD)" = "2811eb262317206ef840eec9312a597ce9916bc8" ] || {
  echo 'T156_DENIED: wrong original Trade source';exit 1;
}
base="$(cd "$(dirname "$0")" && pwd)"
temp="$(mktemp -d /tmp/otc-t156-original-business.XXXXXX)"
trap 'rm -rf "$temp"' EXIT
for kind in order trade; do
  if [ "$kind" = order ]; then source="$order";class=T156OrderRealDomainSnapshotProbe;
  else source="$trade";class=T156TradeRealDomainSnapshotProbe;fi
  mkdir -p "$temp/$kind"
  javac -source 8 -target 8 -cp "$source/target/classes:$source/target/dependency/*" \
    -d "$temp/$kind" "$base/bootstrap/$class.java"
  javap -verbose -classpath "$temp/$kind" "com.app.dc.service.state.$class" |
    grep 'major version: 52' >/dev/null || {
      echo "T156_FAIL: not Java 8 $class" >&2;exit 1;
    }
done
specs=(
  'ordersvr-a OrderSvr P090 OrderSvrA OrderSvrB OrderSvrA'
  'ordersvr-b OrderSvr P090 OrderSvrA OrderSvrB OrderSvrB'
  'ordersvr-b OrderSvr P091 OrderSvrC OrderSvrB OrderSvrB'
  'ordersvr-c OrderSvr P091 OrderSvrC OrderSvrB OrderSvrC'
  'tradesvr-a TradeSvr P090 TradeSvrA TradeSvrB TradeSvrA'
  'tradesvr-b TradeSvr P090 TradeSvrA TradeSvrB TradeSvrB'
)
count=0
staged='|'
for spec in "${specs[@]}"; do
  read -r node service partition a b local <<<"$spec"
  container="otc-t149-ha-intake-$node-1"
  if [ "$service" = OrderSvr ]; then
    kind=order;class=T156OrderRealDomainSnapshotProbe
  else kind=trade;class=T156TradeRealDomainSnapshotProbe;fi
  image="local/otc-t153-${node%%-*}:common-e1-candidate"
  [ "$(docker inspect "$container" --format '{{.State.Running}}')" = true ] &&
  [ "$(docker inspect "$container" --format '{{.Config.Image}}')" = "$image" ] || {
    echo "T156_FAIL: wrong original isolated candidate $container" >&2;exit 1;
  }
  case "$staged" in *"|$node|"*) ;; *)
    docker cp "$temp/$kind/com" "$container:/tmp/"
    staged="${staged}$node|"
  esac
  output="$(docker exec "$container" sh -c \
    "cd /srv/dc/dc/$service && java -cp '/tmp:classes:config:lib/*' \
      com.app.dc.service.state.$class '$partition' '$a' '$b' '$local'")"
  case "$service" in
    OrderSvr) marker=T156_IN_CONTAINER_ORDER_BUSINESS_CAPTURE_AND_RESTORE_ORIGINAL_RSA_PASS;
      deny=T156_ORDER_NONEMPTY_BUSINESS_DENIED_ORIGINAL_EMPTY_RSA_PASS;;
    TradeSvr) marker=T156_IN_CONTAINER_TRADE_BUSINESS_CAPTURE_AND_STAGED_RESTORE_ORIGINAL_RSA_PASS;
      deny=T156_TRADE_NONEMPTY_BUSINESS_DENIED_ORIGINAL_EMPTY_RSA_PASS;;
  esac
  printf '%s\n' "$output" | grep "^$deny partition=$partition node=$local" || {
    echo "T156_FAIL: nonempty source was not rejected by original signed empty Genesis" >&2;exit 1;
  }
  printf '%s\n' "$output" | grep "^$marker partition=$partition node=$local sha=" || {
    echo "T156_FAIL: real domain snapshot or signed Genesis mismatch" >&2;exit 1;
  }
  count=$((count+1))
done
[ "$count" = 6 ]
echo 'T156_REAL_PRODUCTION_DOMAIN_AUXILIARY_IN_CONTAINER_6_OF_6_PASS'
echo 'T156_NO_GO: auxiliary domain JVM cannot prove main business loaded,'
echo 'T156_NO_GO: Common same-ZK-session signed zero-WAL install or READY'