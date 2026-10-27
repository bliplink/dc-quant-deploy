#!/usr/bin/env bash
# T169: build current Common-only Order/Trade ARM64 candidates.
# Only the isolated T149 project may deploy them; this is build-only.
set -euo pipefail
[ "$#" -eq 3 ] || { echo "usage: $0 ORDER_SOURCE TRADE_SOURCE COMMON_JAR" >&2; exit 2; }
order="$1"; trade="$2"; common="$3"
expectedOrder="00f7baf367157b300a5075940a353ddf5f222543"
expectedTrade="6be70252985d79e9fb8f6f3f864bfd99b40500d2"
expectedCommon="f3b63e03598c05476c660d4dc5adf21f83106b84aca79e7d751b2bca92595da3"
[[ "$order" == /* && "$trade" == /* && "$common" == /* ]] || exit 1
test -f "$order/pom.xml" && test -f "$trade/pom.xml" && test -f "$common" || exit 1
test "$(git -C "$order" rev-parse HEAD)" = "$expectedOrder" || { echo WRONG_ORDER_HEAD >&2; exit 1; }
test "$(git -C "$trade" rev-parse HEAD)" = "$expectedTrade" || { echo WRONG_TRADE_HEAD >&2; exit 1; }
test "$(shasum -a 256 "$common" | cut -d ' ' -f1)" = "$expectedCommon" || { echo WRONG_COMMON_SHA >&2; exit 1; }
stage="$(mktemp -d /tmp/otc-t169-two-voter-replay-arm64.XXXXXX)"
trap 'rm -rf -- "$stage"' EXIT
for kind in order trade; do
  if [ "$kind" = order ]; then
    src="$order"; svc=OrderSvr; image=ordersvr
  else
    src="$trade"; svc=TradeSvr; image=tradesvr
  fi
  [ -d "$src/target/classes" ] && [ -d "$src/target/dependency" ] || exit 1
  root="$stage/$image"
  mkdir -p "$root/target/classes" "$root/target/dependency"
  cp "$src/Dockerfile" "$src/docker-entrypoint.sh" "$root/"
  rsync -a "$src/salt-formula/" "$root/salt-formula/"
  rsync -a "$src/target/classes/" "$root/target/classes/"
  rsync -a "$src/target/dependency/" "$root/target/dependency/"
  cp "$common" "$root/target/dependency/$(basename "$common")"
  test "$(find "$root/target/dependency" -maxdepth 1 -name 'com.app.common-*.jar' | wc -l | tr -d ' ')" -eq 1
  test "$(shasum -a 256 "$root/target/dependency/$(basename "$common")" | cut -d ' ' -f1)" = "$expectedCommon"
  tag="local/otc-t169-$image:certified-historical-members"
  if [ "$kind" = order ];then parent="local/otc-t168-ordersvr:verified-serving-domain";else parent="local/otc-t168-tradesvr:verified-serving-domain";fi
  test "$(docker image inspect "$parent" --format '{{.Architecture}}')" = arm64
  docker build --pull=false --build-arg RUNTIME_BASE_IMAGE="$parent" \
    --build-arg SERVICE_NAME="$svc" --build-arg MAIN_CLASS="$svc" \
    -t "$tag" "$root"
  test "$(docker image inspect "$tag" --format '{{.Architecture}}')" = arm64
  docker run --rm --network none --read-only --entrypoint sh "$tag" -c '
    set -eu
    root="/srv/dc/dc/$1"; domain="${1%Svr}"; expected="$2"; source="$3"
    set -- "$root"/lib/com.app.common-*.jar
    test "$#" -eq 1
    test "$(sha256sum "$1" | cut -d " " -f1)" = "$expected"
    test -f "$root/classes/com/app/dc/service/state/$source"
    test -f "$root/classes/com/app/dc/service/state/${domain}CommonRecoveredDomainWiring.class"
    test -f "$root/classes/com/app/dc/service/state/${domain}CommonOriginalSignedSourceWiring.class"
  ' sh "$svc" "$expectedCommon" "${svc%Svr}FencedRecoveringBusinessState.class"
  docker image inspect "$tag" --format 'T169_ARM64_CANDIDATE_PASS {{.Id}} {{.Architecture}}'
done
echo T169_BUILD_ONLY_OFFICIAL_DEMO_UNCHANGED