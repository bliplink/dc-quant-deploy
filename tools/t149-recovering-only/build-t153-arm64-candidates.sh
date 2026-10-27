#!/usr/bin/env bash
# Reproducible local ARM64 candidate build only. No service restarts, no Actions.
# Requires pinned pre-tested T152 Order/Trade local worktrees and T153 Common jar.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo "Usage: bash build-t153-arm64-candidates.sh <absolute-Order-T152-source> <absolute-Trade-T152-source> <absolute-Common-T153-jar>" >&2
  exit 2
fi
order="$1"; trade="$2"; common="$3"
expectedSha="58c71dd41b70cbb4ac97d6ab3887978c5204e2d4a464017257a23908b961f659"
orderCommit="4b1c7d8fce274208f4d6f74d7b70998775ad0a35"
tradeCommit="2811eb262317206ef840eec9312a597ce9916bc8"
for entry in "$order" "$trade"; do
  if [[ "$entry" != /* ]] || [ ! -f "$entry/pom.xml" ]; then
    echo "T153_DENIED: absolute service source checkout required" >&2
    exit 1
  fi
done
if [[ "$common" != /* ]] || [ ! -f "$common" ] ||
   [ "$(shasum -a 256 "$common" | cut -d ' ' -f1)" != "$expectedSha" ] ||
   [ "$(git -C "$order" rev-parse HEAD)" != "$orderCommit" ] ||
   [ "$(git -C "$trade" rev-parse HEAD)" != "$tradeCommit" ]; then
  echo "T153_DENIED: source commits or original Common candidate binary not pinned" >&2
  exit 1
fi
mvn="/Users/kong/.opentradingcore/local-ha-build-20261015/tools/apache-maven-3.9.11/bin/mvn"
test -x "$mvn"
for source in "$order" "$trade"; do
  ( cd "$source" && "$mvn" -q -o -DskipTests package )
done
stage="$(mktemp -d /tmp/otc-t153-arm64-source.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
for label in order trade; do
  if [ "$label" = order ]; then
    src="$order"; svc=OrderSvr
    parent="local/otc-t145-ordersvr:certified-pending-newing"
    tag="local/otc-t153-ordersvr:common-e1-candidate"
  else
    src="$trade"; svc=TradeSvr
    parent="local/otc-t148-tradesvr:real-certified-newing-netty"
    tag="local/otc-t153-tradesvr:common-e1-candidate"
  fi
  dest="$stage/$label"
  mkdir -p "$dest/target" "$dest/salt-formula"
  cp "$src/Dockerfile" "$src/docker-entrypoint.sh" "$dest/"
  rsync -a "$src/salt-formula/" "$dest/salt-formula/"
  rsync -a "$src/target/classes/" "$dest/target/classes/"
  rsync -a "$src/target/dependency/" "$dest/target/dependency/"
  jarname="$(basename "$common")"
  test -f "$dest/target/dependency/$jarname" || {
    echo "T153_DENIED: service Common Maven GAV differs from pinned T153" >&2
    exit 1
  }
  cp "$common" "$dest/target/dependency/$jarname"
  count="$(find "$dest/target/dependency" -maxdepth 1 -name 'com.app.common-*.jar' | wc -l | tr -d ' ')"
  test "$count" -eq 1
  test "$(shasum -a 256 "$dest/target/dependency/$jarname" | cut -d ' ' -f1)" = "$expectedSha"
  docker image inspect "$parent" --format '{{.Architecture}}' | grep -qx arm64
  if [ "$label" = order ]; then
    docker build --pull=false --build-arg RUNTIME_BASE_IMAGE="$parent" \
      --build-arg SERVICE_NAME="$svc" --build-arg MAIN_CLASS="$svc" \
      --build-arg SERVICE_REVISION="$orderCommit" \
      --build-arg COMMON_REVISION="ecab5b9f7d91dc41c01dadd8dd2eaa0327f10c02" \
      --build-arg COMMON_JAR_SHA256="$expectedSha" \
      -t "$tag" "$dest"
  else
    docker build --pull=false --build-arg RUNTIME_BASE_IMAGE="$parent" \
      --build-arg SERVICE_NAME="$svc" --build-arg MAIN_CLASS="$svc" \
      -t "$tag" "$dest"
  fi
  test "$(docker image inspect "$tag" --format '{{.Architecture}}')" = arm64
  docker run --rm --network none --read-only --entrypoint sh "$tag" -c '
    set -eu
    expected="$2"
    dir="/srv/dc/dc/$1/lib"
    set -- "$dir"/com.app.common-*.jar
    [ "$#" -eq 1 ] && [ -f "$1" ]
    [ "$(sha256sum "$1" | cut -d " " -f1)" = "$expected" ]
  ' sh "$svc" "$expectedSha"
  echo "T153_ARM64_IMMUTABLE_SOURCE_PINNED_COMMON_JAR_BUILT_PASS $tag"
done
echo "T153_BUILD_ONLY: actual T149 Compose is NOT changed by this script"