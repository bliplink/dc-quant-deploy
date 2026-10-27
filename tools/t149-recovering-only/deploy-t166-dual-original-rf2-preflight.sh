#!/usr/bin/env bash
# Only update the already physically-certified T164 recovery-only lab.
# No official Demo/Robot/production ZK mutation and NEVER publishes READY.
set -euo pipefail
[ "$#" -eq 1 ] || { echo "usage: $0 /absolute/t164-fresh-e1-runtime-20261026" >&2; exit 2; }
root="$1"
[[ "$root" == /* && "$(basename "$root")" == t164-fresh-e1-runtime-20261026 ]] || exit 1
base="$root/compose.yaml"
trade="$root/compose.trade-t164-fix.yaml"
peers="$root/compose.t166-original-rf2-ready-preflight.yaml"
test -f "$base" && test -f "$trade" && test -f "$peers"
sha="991579637320bfdb37458e638d701ab9a2861b70f1782b3fe402652a70b5653c"
for kind in ordersvr tradesvr;do
 image="local/otc-t166-$kind:both-original-replay"
 test "$(docker image inspect "$image" --format '{{.Architecture}}')" = arm64
 service="OrderSvr";[ "$kind" = tradesvr ] && service="TradeSvr"
 docker run --rm --network none --read-only --entrypoint sh "$image" -c '
    set -eu; expected="$1"; service="$2"
    set -- "/srv/dc/dc/$service"/lib/com.app.common-*.jar
    [ "$#" -eq 1 ]
    [ "$(sha256sum "$1" | cut -d " " -f1)" = "$expected" ]
 ' sh "$sha" "$service"
done
docker compose --project-directory "$root" -f "$base" -f "$trade" -f "$peers" config --format json | python3 -c '
import json,sys
x=json.load(sys.stdin)
assert x["name"]=="otc-t164-new-original-e1"
names=["ordersvr-a164","ordersvr-b164","tradesvr-a164","tradesvr-b164"]
assert sorted(x["services"])==sorted(names)
for n in names:
 c=x["services"][n]
 assert c["image"]=="local/otc-t166-"+n.split("-")[0]+":both-original-replay"
 assert not c.get("ports")
 mounts=c["volumes"]
 targets={i["target"] for i in mounts}
 assert len(mounts)>=8 and "/srv/dc/data" in targets
 assert "/srv/dc/original-e1-other/genesis/P090" in targets
 assert "/srv/dc/original-e1-other/install" in targets
print("T166_FOUR_EXACT_SERVICE_MOUNTS_NO_PUBLISHED_PORTS_PASS")
'
for name in ordersvr-a ordersvr-b tradesvr-a tradesvr-b;do
  cfg="$root/config/$name/application.properties"
  kind=order;[[ "$name" == tradesvr* ]] && kind=trade
  grep -Fx "$kind.common.nodeRuntime.freshE1.P090.requireBothOriginalReplay=true" "$cfg" >/dev/null
  grep -Fx "$kind.common.nodeRuntime.phase=RECOVERING" "$cfg" >/dev/null
  phase="$root/data/$name/t164-e1-install/P090/ledger/P090.recovery"
  grep -Fx 'phase=REPLAY_COMPLETE' "$phase" >/dev/null
done
orig_zk=""
for n in zk1 zk2 zk3;do
  orig_zk="$orig_zk $(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.Id}}')"
done
echo T166_START_REAL_JVM_BOTH_VOTER_PHYSICAL_ATTESTATION
for name in ordersvr-a ordersvr-b tradesvr-a tradesvr-b;do
  candidate="otc-t164-new-original-e1-${name}164-1"
  case "$name" in
    ordersvr-a) expectedNode=OrderSvrA;expectedImage=ordersvr;;
    ordersvr-b) expectedNode=OrderSvrB;expectedImage=ordersvr;;
    tradesvr-a) expectedNode=TradeSvrA;expectedImage=tradesvr;;
    tradesvr-b) expectedNode=TradeSvrB;expectedImage=tradesvr;;
  esac
  image="$(docker inspect "$candidate" --format '{{.Config.Image}}' 2>/dev/null || true)"
  running="$(docker inspect "$candidate" --format '{{.State.Running}}' 2>/dev/null || true)"
  if [ "$image" != "local/otc-t166-$expectedImage:both-original-replay" ] || [ "$running" != true ];then
    docker compose --project-directory "$root" -f "$base" -f "$trade" -f "$peers" \
      up -d --no-deps --force-recreate "${name}164"
    sleep 11
  fi
  if [ "$(docker inspect "$candidate" --format '{{.State.Running}}')" != true ];then
    docker logs --tail 110 "$candidate" 2>&1 | \
      grep -F 'recovering node lease owned by another ZK session' >/dev/null || {
        docker logs --tail 50 "$candidate" >&2
        exit 1
      }
    sleep 12
    docker compose --project-directory "$root" -f "$base" -f "$trade" -f "$peers" \
      start "${name}164"
    sleep 10
  fi
  if [ "$(docker inspect "$candidate" --format '{{.State.Running}}')" != true ];then
    docker logs --tail 100 "$candidate" >&2;exit 1
  fi
  docker logs --tail 150 "$candidate" 2>&1 | \
    grep -F 'T166_COMMON_ORIGINAL_E1_SAME_ZK_BOTH_REPLAY_COMPLETE_PASS' | \
    grep -F "node=$expectedNode" | \
    grep -F 'ready=false' >/dev/null || {
      echo "T166_REAL_SAME_SESSION_PEER_ATTESTATION_MISSING $name" >&2
      docker logs --tail 70 "$candidate" >&2
      exit 1
    }
  grep -Fx 'phase=REPLAY_COMPLETE' "$root/data/$name/t164-e1-install/P090/ledger/P090.recovery" >/dev/null
  echo "T166_ACTUAL_ORIGINAL_ZK_SESSION_AND_TWO_PHYSICAL_VOTERS_PASS $name"
done
current_zk=""
for n in zk1 zk2 zk3;do
  current_zk="$current_zk $(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.Id}}')"
done
test "$orig_zk" = "$current_zk" || { echo T166_ORIGINAL_ZK_MODIFIED >&2;exit 1; }
echo T166_FOUR_CERTIFIED_JVMS_RECOVERING_ONLY_NO_ROBOT_BUSINESS_PORTS_PASS