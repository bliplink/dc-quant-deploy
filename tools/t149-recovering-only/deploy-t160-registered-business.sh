#!/usr/bin/env bash
# T160: replace ONLY five original T149 isolated RECOVERING test candidates
# with Common-fenced in-main-JVM Order/Trade inspection images.
# No routes, REST, Gateway/Robot, external business ports, ZK READY or ACK.
set -euo pipefail
if [ "$#" -ne 1 ];then
  echo 'Usage: deploy-t160-fenced-inspection.sh <original-T149-runtime-root>' >&2;exit 2
fi
root="$1"
if [[ "$root" != /* ]] || [ "$(basename "$root")" != t149-order-trade-deploy-20261026 ] ||
   [ ! -f "$root/compose.yaml" ] ||
   [ ! -f "$root/t160-fenced-inspection/compose.t160.yaml" ];then
  echo T160_DENIED_NOT_EXACT_ISOLATED_T149_RUNTIME >&2;exit 1
fi
overlay="$root/t160-fenced-inspection/compose.t160.yaml"
expected="f58acf90fd955b0edd50017b6bdf232949600e6af4fad37b090d97b3ddfce2a0"
for pair in 'ordersvr OrderSvr' 'tradesvr TradeSvr';do
  read -r kind svc <<< "$pair"
  image="local/otc-t160-$kind:registered-business-recovering"
  [ "$(docker image inspect "$image" --format '{{.Architecture}}')" = arm64 ] || exit 1
  docker run --rm --network none --read-only --entrypoint sh "$image" -c '
    set -eu
    root="/srv/dc/dc/$1";expected="$2"
    set -- "$root"/lib/com.app.common-*.jar
    [ "$#" -eq 1 ] && [ -f "$1" ] || exit 1
    test "$(sha256sum "$1" | cut -d " " -f1)" = "$expected"
  ' sh "$svc" "$expected"
done
zk_before=''
for zk in zk1 zk2 zk3;do
  zk_before="$zk_before $(docker inspect "otc-t149-ha-intake-$zk-1" --format '{{.Id}}')"
done
t84_before=''
for node in a b;do
  t84_before="$t84_before $(docker inspect "otc-t84-source-integrated-otc-ha-demo-$node-1" --format '{{.Id}}')"
done
docker compose --project-directory "$root" -f "$root/compose.yaml" -f "$overlay" \
  --profile business up -d --no-deps --force-recreate \
  ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b
# Docker Started != JVM recovered. Old ZK ephemeral lease can still belong
# to retired process until the existing 8s session expiration. Never delete
# or modify it; one natural-lease-expiry retry is allowed ONLY for that error.
sleep 10
retry=''
for node in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b;do
  container="otc-t149-ha-intake-$node-1"
  if [ "$(docker inspect "$container" --format '{{.State.Running}}')" != true ];then
    if ! docker logs --tail 130 "$container" 2>&1 |
      grep -F 'recovering node lease owned by another ZK session' >/dev/null;then
      echo "T160_FAIL unexpected JVM startup rejection: $node" >&2
      docker logs --tail 13 "$container" >&2
      exit 1
    fi
    retry="$retry $node"
  fi
done
if [ -n "$retry" ];then
  echo T160_EXPECTED_OLD_ZK_SESSION_FENCE_WAITING_FOR_NATURAL_EXPIRY
  sleep 12
  # word splitting is intentional for the exact whitelist above
  # shellcheck disable=SC2086
  docker compose --project-directory "$root" -f "$root/compose.yaml" -f "$overlay" \
    --profile business start $retry
fi
sleep 12
zk_after=''
for zk in zk1 zk2 zk3;do
  zk_after="$zk_after $(docker inspect "otc-t149-ha-intake-$zk-1" --format '{{.Id}}')"
done
test "$zk_before" = "$zk_after" || { echo T160_FAIL_ISOLATED_ZK_WAS_RECREATED >&2;exit 1; }
t84_after=''
for node in a b;do
  t84_after="$t84_after $(docker inspect "otc-t84-source-integrated-otc-ha-demo-$node-1" --format '{{.Id}}')"
done
test "$t84_before" = "$t84_after" || { echo T160_FAIL_ORIGINAL_DEMO_WAS_RECREATED >&2;exit 1; }
for node in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b;do
  container="otc-t149-ha-intake-$node-1"
  tag="local/otc-t160-${node%%-*}:registered-business-recovering"
  [ "$(docker inspect "$container" --format '{{.State.Running}}')" = true ] || {
    echo "T160_FAIL JVM exited after stability window: $node" >&2;exit 1;
  }
  [ "$(docker inspect "$container" --format '{{.Config.Image}}')" = "$tag" ] || exit 1
  binding="$(docker inspect "$container" --format '{{json .HostConfig.PortBindings}}')"
  [ "$binding" = null ] || [ "$binding" = "{}" ] || {
    echo T160_FAIL_EXTERNAL_BUSINESS_PORT_OPEN >&2;exit 1;
  }
  case "$node" in
    ordersvr-*) marker=T157_COMMON_ZK_FENCED_ORDER_MAIN_JVM_BUSINESS_INSPECTION_PASS ;;
    tradesvr-*) marker=T157_COMMON_ZK_FENCED_TRADE_MAIN_JVM_BUSINESS_INSPECTION_PASS ;;
  esac
  if ! docker logs --tail 150 "$container" 2>&1 |
    grep -F "$marker" | grep -F 'ready=false durableInstall=false' >/dev/null;then
    echo "T160_FAIL no same-process actual business state proof: $node" >&2
    docker logs --tail 20 "$container" >&2;exit 1
  fi
  echo "T160_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS $node"
done
echo T160_FIVE_REAL_MAIN_JVMS_BUSINESS_STATE_LOADED_ZK3_T84_UNCHANGED_PASS
echo T160_NO_GO: historical zero-WAL/Custody, durable real install and READY not yet certified