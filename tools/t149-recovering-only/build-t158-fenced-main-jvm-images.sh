#!/usr/bin/env bash
# T158: reproducible local ARM64 build for the ALREADY validated main-JVM
# inspection candidate. Does not deploy, touch ZK, Robot or official Demo.
set -euo pipefail
if [ "$#" -ne 3 ];then
  echo 'Usage: build-t158-fenced-main-jvm-images.sh <Order-src> <Trade-src> <pinned-Common-jar>' >&2
  exit 2
fi
order="$1";trade="$2";common="$3"
expectedOrder="7735d8b51fb734ea7be31cab55bbe9e609f31431"
expectedTrade="b771a3bed3a2e72661c01f05b74c65c758ca2e45"
expectedCommon="0c7fc859ad9a1d141d157bc252f4a54ab65c0fff78321ca413f3d4a33d926925"
for source in "$order" "$trade";do
  [[ "$source" == /* ]] && [ -f "$source/pom.xml" ] &&
    [ -d "$source/target/classes" ] &&
    [ -d "$source/target/dependency" ] || {
    echo T158_DENIED_SOURCE_NOT_ABSOLUTE_OR_BUILT >&2;exit 1;
  }
done
[[ "$common" == /* ]] && [ -f "$common" ] || exit 1
[ "$(git -C "$order" rev-parse HEAD)" = "$expectedOrder" ] || {
  echo T158_DENIED_WRONG_ORDER_COMMIT >&2;exit 1;
}
[ "$(git -C "$trade" rev-parse HEAD)" = "$expectedTrade" ] || {
  echo T158_DENIED_WRONG_TRADE_COMMIT >&2;exit 1;
}
[ "$(shasum -a 256 "$common" | cut -d ' ' -f1)" = "$expectedCommon" ] || {
  echo T158_DENIED_UNTESTED_COMMON_BINARY >&2;exit 1;
}
stage="$(mktemp -d /tmp/otc-t158-main-jvm-rebuild.XXXXXX)"
trap 'rm -rf -- "$stage"' EXIT
for kind in order trade;do
  if [ "$kind" = order ];then
    source="$order";service=OrderSvr;image=ordersvr
  else
    source="$trade";service=TradeSvr;image=tradesvr
  fi
  context="$stage/$kind"
  mkdir -p "$context/target" "$context/salt-formula"
  cp "$source/Dockerfile" "$source/docker-entrypoint.sh" "$context/"
  rsync -a "$source/salt-formula/" "$context/salt-formula/"
  rsync -a "$source/target/classes/" "$context/target/classes/"
  rsync -a "$source/target/dependency/" "$context/target/dependency/"
  cp "$common" "$context/target/dependency/$(basename "$common")"
  test "$(find "$context/target/dependency" -maxdepth 1 -name 'com.app.common-*.jar' | wc -l | tr -d ' ')" -eq 1
  test "$(shasum -a 256 "$context/target/dependency/$(basename "$common")" | cut -d ' ' -f1)" = "$expectedCommon"
  test -f "$context/target/classes/com/app/dc/service/state/${service%Svr}FencedRecoveringBusinessState.class"
  tag="local/otc-t158-$image:fenced-main-jvm"
  parent="local/otc-t153-$image:common-e1-candidate"
  test "$(docker image inspect "$parent" --format '{{.Architecture}}')" = arm64
  docker build --pull=false --build-arg RUNTIME_BASE_IMAGE="$parent" \
    --build-arg SERVICE_NAME="$service" --build-arg MAIN_CLASS="$service" \
    -t "$tag" "$context"
  test "$(docker image inspect "$tag" --format '{{.Architecture}}')" = arm64
  docker run --rm --network none --read-only --entrypoint sh "$tag" -c '
    set -eu
    root="/srv/dc/dc/$1";expected="$2";business="$3"
    set -- "$root"/lib/com.app.common-*.jar
    [ "$#" = 1 ] && [ -f "$1" ] &&
      [ "$(sha256sum "$1" | cut -d " " -f1)" = "$expected" ] &&
      [ -f "$root/classes/com/app/dc/service/state/$business" ]
  ' sh "$service" "$expectedCommon" "${service%Svr}FencedRecoveringBusinessState.class"
  docker image inspect "$tag" --format 'T158_REPRODUCIBLE_IMAGE_BUILT_PASS {{.Id}} {{.Architecture}}'
done
echo 'T158_BUILD_ONLY_NO_SERVICE_REPLACEMENT'