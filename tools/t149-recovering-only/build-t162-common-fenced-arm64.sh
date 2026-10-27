#!/usr/bin/env bash
# T162: build current Common-only Order/Trade ARM64 candidates.
# Only the isolated T149 project may deploy them; this is build-only.
set -euo pipefail
[ "$#" -eq 3 ] || { echo "usage: $0 ORDER_SOURCE TRADE_SOURCE COMMON_JAR" >&2; exit 2; }
order="$1"; trade="$2"; common="$3"
expectedOrder="0fe187f0171e8db8c4cf5e9bcd407de85029f51b"
expectedTrade="c47e0bab48f474f65c7b7bae847863c9f598b003"
expectedCommon="6324dbdf2f855f9cb54bac22ddd6ba6d5235b1ba5a28b4a9c865e952911c899b"
[[ "$order" == /* && "$trade" == /* && "$common" == /* ]] || exit 1
test -f "$order/pom.xml" && test -f "$trade/pom.xml" && test -f "$common" || exit 1
test "$(git -C "$order" rev-parse HEAD)" = "$expectedOrder" || { echo WRONG_ORDER_HEAD >&2; exit 1; }
test "$(git -C "$trade" rev-parse HEAD)" = "$expectedTrade" || { echo WRONG_TRADE_HEAD >&2; exit 1; }
test "$(shasum -a 256 "$common" | cut -d ' ' -f1)" = "$expectedCommon" || { echo WRONG_COMMON_SHA >&2; exit 1; }
stage="$(mktemp -d /tmp/otc-t162-common-business-arm64.XXXXXX)"
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
  tag="local/otc-t162-$image:common-fenced-intake"
  parent="local/otc-t160-$image:registered-business-recovering"
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
  docker image inspect "$tag" --format 'T162_ARM64_CANDIDATE_PASS {{.Id}} {{.Architecture}}'
done
echo T162_BUILD_ONLY_OFFICIAL_DEMO_UNCHANGED