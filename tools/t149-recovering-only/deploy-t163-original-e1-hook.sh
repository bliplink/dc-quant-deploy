#!/usr/bin/env bash
# T163: redeploy only the five previously isolated T149 RECOVERING JVMs.
# Never change the official Demo/Gateway/Robot, READY, original ZK, or RSA.
set -euo pipefail
[ "$#" -eq 1 ] || { echo "usage: $0 /absolute/T149-isolated-root" >&2; exit 2; }
root="$1"
[[ "$root" == /* && "$(basename "$root")" == "t149-order-trade-deploy-20261026" ]] || exit 1
base="$root/compose.yaml"
t160="$root/t160-fenced-inspection/compose.t160.yaml"
[ -f "$base" ] && [ -f "$t160" ] || { echo T163_ISOLATED_CONFIGURATION_MISSING >&2; exit 1; }
expected="1f155c487ad1730744824cac80c77ecdfa8efcba78de6fb3dff0c8f79ac44208"
stage="$root/t163-original-e1-hook"
mkdir -p "$stage"
overlay="$stage/compose.t163.yaml"
cat > "$overlay" <<'YAML'
services:
  ordersvr-a:
    image: local/otc-t163-ordersvr:original-e1-install-hook
  ordersvr-b:
    image: local/otc-t163-ordersvr:original-e1-install-hook
  ordersvr-c:
    image: local/otc-t163-ordersvr:original-e1-install-hook
  tradesvr-a:
    image: local/otc-t163-tradesvr:original-e1-install-hook
  tradesvr-b:
    image: local/otc-t163-tradesvr:original-e1-install-hook
YAML
for kind in ordersvr tradesvr;do
  tag="local/otc-t163-$kind:original-e1-install-hook"
  test "$(docker image inspect "$tag" --format '{{.Architecture}}')" = arm64
  if [ "$kind" = ordersvr ]; then service=OrderSvr;else service=TradeSvr;fi
  docker run --rm --network none --read-only --entrypoint sh "$tag" -c '
    set -eu; root="/srv/dc/dc/$1"; digest="$2"
    set -- "$root"/lib/com.app.common-*.jar
    test "$#" -eq 1 && test "$(sha256sum "$1" | cut -d " " -f1)" = "$digest"
  ' sh "$service" "$expected"
done
docker compose --project-directory "$root" -f "$base" -f "$t160" -f "$overlay" \
    --profile business config --format json | python3 -c '
import sys,json
c=json.load(sys.stdin);assert c["name"]=="otc-t149-ha-intake"
for node in ["ordersvr-a","ordersvr-b","ordersvr-c","tradesvr-a","tradesvr-b"]:
 s=c["services"][node]
 assert s["image"]=="local/otc-t163-"+node.split("-")[0]+":original-e1-install-hook"
 assert not s.get("ports")
 assert any(v["target"].endswith("/config/application.properties") and
            v["read_only"] for v in s["volumes"])
print("T163_FIVE_CANDIDATE_COMPOSE_NO_PUBLIC_PORT_PASS")
'
before_zk=""
before_t84=""
for n in zk1 zk2 zk3; do
  before_zk="$before_zk $(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.Id}}')"
done
for n in a b; do
  before_t84="$before_t84 $(docker inspect "otc-t84-source-integrated-otc-ha-demo-$n-1" --format '{{.Id}}')"
done
docker compose --project-directory "$root" -f "$base" -f "$t160" -f "$overlay" \
    --profile business up -d --no-deps --force-recreate \
    ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b
# Prior original voter leases must naturally expire. Do not erase ZK or WAL.
sleep 12
retry=""
for n in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b;do
  if [ "$(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.State.Running}}')" != true ];then
    docker logs --tail 100 "otc-t149-ha-intake-$n-1" 2>&1 | grep -F \
      'recovering node lease owned by another ZK session' >/dev/null || {
      echo "T163_NONLEASE_JVM_FAILURE $n" >&2;exit 1;
    }
    retry="$retry $n"
  fi
done
if [ -n "$retry" ];then
  sleep 12
  # shellcheck disable=SC2086
  docker compose --project-directory "$root" -f "$base" -f "$t160" -f "$overlay" \
      --profile business start $retry
fi
sleep 12
after_zk=""
after_t84=""
for n in zk1 zk2 zk3; do
  after_zk="$after_zk $(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.Id}}')"
done
for n in a b; do
  after_t84="$after_t84 $(docker inspect "otc-t84-source-integrated-otc-ha-demo-$n-1" --format '{{.Id}}')"
done
test "$before_zk" = "$after_zk" || { echo T163_ZK_CHANGED >&2;exit 1; }
test "$before_t84" = "$after_t84" || { echo T163_ORIGINAL_DEMO_CHANGED >&2;exit 1; }
for n in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b;do
  container="otc-t149-ha-intake-$n-1"
  [ "$(docker inspect "$container" --format '{{.State.Running}}')" = true ] || {
    echo "T163_NOT_RUNNING $n" >&2; docker logs --tail 35 "$container" >&2;exit 1;
  }
  case "$n" in
    ordersvr-*) marker=T157_COMMON_ZK_FENCED_ORDER_MAIN_JVM_BUSINESS_INSPECTION_PASS;;
    tradesvr-*) marker=T157_COMMON_ZK_FENCED_TRADE_MAIN_JVM_BUSINESS_INSPECTION_PASS;;
  esac
  docker logs --tail 150 "$container" 2>&1 | grep -F "$marker" | \
      grep -F 'ready=false durableInstall=false' >/dev/null || {
    echo "T163_REAL_DOMAIN_CENSUS_INCOMPLETE $n" >&2;exit 1;
  }
  echo "T163_COMMON_ZK_RSA_REAL_MAIN_JVM_FENCED_PASS $n"
done
echo T163_ISOLATED_FIVE_RUNNING_ZK3_T84_UNCHANGED_PASS
echo T163_ROBOT_LIVE_QUOTES_NOT_YET_READY