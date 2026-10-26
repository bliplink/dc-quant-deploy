#!/usr/bin/env bash
# T164: build current Common-only Order/Trade ARM64 candidates.
# Only the isolated T149 project may deploy them; this is build-only.
set -euo pipefail
[ "$#" -eq 3 ] || { echo "usage: $0 ORDER_SOURCE TRADE_SOURCE COMMON_JAR" >&2; exit 2; }
order="$1"; trade="$2"; common="$3"
expectedOrder="b2516b51e5d162de84d004771ae3a620f81d9f99"
expectedTrade="2b1d0f8d5e11d4a1d2a8b7374bceb3bbdf4448b9"
expectedCommon="1f155c487ad1730744824cac80c77ecdfa8efcba78de6fb3dff0c8f79ac44208"
[[ "$order" == /* && "$trade" == /* && "$common" == /* ]] || exit 1
test -f "$order/pom.xml" && test -f "$trade/pom.xml" && test -f "$common" || exit 1
test "$(git -C "$order" rev-parse HEAD)" = "$expectedOrder" || { echo WRONG_ORDER_HEAD >&2; exit 1; }
test "$(git -C "$trade" rev-parse HEAD)" = "$expectedTrade" || { echo WRONG_TRADE_HEAD >&2; exit 1; }
test "$(shasum -a 256 "$common" | cut -d ' ' -f1)" = "$expectedCommon" || { echo WRONG_COMMON_SHA >&2; exit 1; }
stage="$(mktemp -d /tmp/otc-t164-common-business-arm64.XXXXXX)"
trap 'rm -rf -- "$stage"' EXIT
for kind in trade; do
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
  tag="local/otc-t164-$image:fenced-trade-replay-fix"
  parent="local/otc-t163-$image:original-e1-install-hook"
  test "$(docker image inspect "$parent" --format '{{.Architecture}}')" = arm64
  docker build --pull=false --build-arg RUNTIME_BASE_IMAGE="$parent" \
    --build-arg SERVICE_NAME="$svc" --build-arg MAIN_CLASS="$svc" \
    -t "$tag" "$root"
  test "$(docker image inspect "$tag" --format '{{.Architecture}}')" = arm64
  docker run --rm --network none --read-only --entrypoint sh "$tag" -c '
    set -eu
    root="/srv/dc/dc/$1"; expected="$2"; source="$3"
    set -- "$root"/lib/com.app.common-*.jar
    test "$#" -eq 1
    test "$(sha256sum "$1" | cut -d " " -f1)" = "$expected"
    test -f "$root/classes/com/app/dc/service/state/$source"
  ' sh "$svc" "$expectedCommon" "${svc%Svr}FencedRecoveringBusinessState.class"
  docker image inspect "$tag" --format 'T164_ARM64_CANDIDATE_PASS {{.Id}} {{.Architecture}}'
done
echo T164_BUILD_ONLY_OFFICIAL_DEMO_UNCHANGED