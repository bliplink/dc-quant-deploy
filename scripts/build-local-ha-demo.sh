#!/usr/bin/env bash
set -euo pipefail

# Native macOS development-only: local source -> local Maven artifacts -> local images.
# No Maven Central publish, GitHub Actions push, or live container replacement.
# Run from Mac after selecting explicit source worktrees below.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${OTC_LOCAL_BUILD_ROOT:-${HOME}/.opentradingcore/local-ha-validation}"
COMMON_SOURCE="${OTC_COMMON_SOURCE:?Set OTC_COMMON_SOURCE to the common source worktree}"
DC_SOURCE="${OTC_DC_SOURCE:?Set OTC_DC_SOURCE to the com.app.dc checkout}"
ORDER_SOURCE="${OTC_ORDER_SOURCE:?Set OTC_ORDER_SOURCE to the OrderSvr worktree}"
TRADE_SOURCE="${OTC_TRADE_SOURCE:?Set OTC_TRADE_SOURCE to the TradeSvr worktree}"
MD_SOURCE="${OTC_MD_SOURCE:?Set OTC_MD_SOURCE to the MDSvr worktree}"
MAVEN_IMAGE="${OTC_MAVEN_IMAGE:-maven:3.8.8-eclipse-temurin-8}"

log() { printf '[local-ha-build] %s\n' "$*"; }
fail() { printf '[local-ha-build] ERROR: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail "Docker is required"
command -v python3 >/dev/null || fail "Python 3 is required"
command -v git >/dev/null || fail "Git is required"
for p in "$COMMON_SOURCE" "$DC_SOURCE" "$ORDER_SOURCE" "$TRADE_SOURCE" "$MD_SOURCE"; do
  [[ -f "$p/pom.xml" ]] || fail "missing Maven project: $p"
done
[[ "$BUILD_ROOT" == /* && "$BUILD_ROOT" != "/" ]] || fail "build root must be an absolute non-root path"
if [[ -e "$BUILD_ROOT/source" && "${OTC_RESUME_BUILD:-false}" != "true" ]]; then
  fail "build root source already exists; set OTC_RESUME_BUILD=true to resume the immutable source snapshot"
fi
mkdir -p "$BUILD_ROOT/source" "$BUILD_ROOT/artifacts"
[[ ! -e "$BUILD_ROOT/.lock" ]] || fail "build already locked"
mkdir "$BUILD_ROOT/.lock"
trap 'rmdir "$BUILD_ROOT/.lock" 2>/dev/null || true' EXIT

# Snapshot the exact working copies, including uncommitted edits. Do not build
# against an old origin branch or modify the actual developer worktree.
if [[ "${OTC_RESUME_BUILD:-false}" != "true" ]]; then
names=(common dc ordersvr tradesvr mdsvr)
sources=("$COMMON_SOURCE" "$DC_SOURCE" "$ORDER_SOURCE" "$TRADE_SOURCE" "$MD_SOURCE")
for i in 0 1 2 3 4; do
  name="${names[$i]}"
  src="${sources[$i]}"
  mkdir -p "$BUILD_ROOT/source/$name"
  tar -C "$src" --exclude=.git --exclude=target --exclude=.idea \
    --exclude=.env --exclude='.env.*' --exclude=.secrets --exclude=node_modules \
    --exclude=.mvn/wrapper/maven-wrapper.jar -cf - . \
    | tar -C "$BUILD_ROOT/source/$name" -xf -
  git -C "$src" rev-parse HEAD > "$BUILD_ROOT/artifacts/$name.sha"
  git -C "$src" status --porcelain > "$BUILD_ROOT/artifacts/$name.worktree-changes.txt"
  log "$name source: $(head -c 12 "$BUILD_ROOT/artifacts/$name.sha") (copy preserves uncommitted edits)"
done
common_sha="$(cut -c1-8 "$BUILD_ROOT/artifacts/common.sha")"
local_version="3.0.17-dev${common_sha}-SNAPSHOT"

python3 - "$BUILD_ROOT/source/common/pom.xml" "$BUILD_ROOT/source/dc/pom.xml" "$local_version" <<'PY'
from pathlib import Path
import sys
common=Path(sys.argv[1]); dc=Path(sys.argv[2]); version=sys.argv[3]
import re
c=common.read_text()
c, cn = re.subn(r'(<artifactId>com[.]app[.]common</artifactId>\s*<version>)[^<]+(</version>)',
                lambda m: m.group(1)+version+m.group(2), c, count=1)
assert cn == 1, 'Unable to set the Common development version'
common.write_text(c)
d=dc.read_text()
assert '<artifactId>com.app.common</artifactId>' in d, "Missing common dependency"
d, n = re.subn(r'(<artifactId>com[.]app[.]common</artifactId>\s*<version>)[^<]+(</version>)',
               lambda m: m.group(1)+version+m.group(2), d, count=1)
assert n == 1, "Cannot rewrite com.app.dc common dependency"
dc.write_text(d)
PY

fi

common_sha="$(cut -c1-8 "$BUILD_ROOT/artifacts/common.sha")"
local_version="3.0.17-dev${common_sha}-SNAPSHOT"

# Reuse existing Maven dependency cache for speed, but the development Common
# GAV is UNIQUE and cannot be mistaken for the official 3.0.17 release.
maven() {
  name="$1"; shift
  docker run --rm --cpus=1.5 --memory=2200m \
    -v "$BUILD_ROOT/source/$name:/workspace" \
    -v "$HOME/.m2:/root/.m2" -w /workspace \
    "$MAVEN_IMAGE" mvn -q "$@"
}
log "Compiling local Common GAV io.github.bliplink:com.app.common:$local_version"
maven common install -DskipTests
log "Compiling local com.app.dc module"
maven dc install -DskipTests

# Shared business-independent binaries MUST be byte-identical across images.
common_jar="$HOME/.m2/repository/io/github/bliplink/com.app.common/$local_version/com.app.common-$local_version.jar"
[[ -s "$common_jar" ]] || fail "local Common JAR not installed: $common_jar"
common_digest="$(shasum -a 256 "$common_jar" | awk '{print $1}')"
tag="local-c${common_sha}-$(date -u '+%Y%m%d%H%M%S')"
declare -a images=()
for name in ordersvr tradesvr mdsvr; do
  log "Compiling $name against local Common $local_version"
  maven "$name" package dependency:copy-dependencies -DskipTests -DoutputDirectory=target/dependency
  dep="$BUILD_ROOT/source/$name/target/dependency"
  count="$(find "$dep" -maxdepth 1 -type f -name 'com.app.common-*.jar' | wc -l | tr -d ' ')"
  [[ "$count" -eq 1 ]] || fail "$name must have one Common dependency, found $count"
  jar="$(find "$dep" -maxdepth 1 -type f -name 'com.app.common-*.jar' -print -quit)"
  [[ "$(shasum -a 256 "$jar" | awk '{print $1}')" == "$common_digest" ]] \
    || fail "$name compiled with different Common JAR"
  image="dc-saas/$name:$tag"
  log "Building $image"
  # The production JRE base may not be locally cached and Docker Hub may be
  # unreachable. For DEV VALIDATION ONLY use the already cached Temurin JDK 8
  # builder image. The real service Dockerfile remains unchanged.
  head -n 1 "$BUILD_ROOT/source/$name/Dockerfile" | grep -Fx 'FROM eclipse-temurin:8-jre' >/dev/null \
    || fail "unsupported $name base image for local fallback"
  sed '1s|^FROM eclipse-temurin:8-jre$|FROM maven:3.8.8-eclipse-temurin-8|' \
    "$BUILD_ROOT/source/$name/Dockerfile" > "$BUILD_ROOT/source/$name/Dockerfile.local"
  docker build --pull=false -f "$BUILD_ROOT/source/$name/Dockerfile.local" \
    --label "dc.build.kind=mac-local-ha-demo" \
    --label "dc.common.sha256=$common_digest" \
    --label "dc.common.gav=io.github.bliplink:com.app.common:$local_version" \
    --label "dc.source.revision=$(head -c 40 "$BUILD_ROOT/artifacts/$name.sha")" \
    -t "$image" "$BUILD_ROOT/source/$name"
  images+=("$name=$image")
done

manifest="$BUILD_ROOT/artifacts/local-ha-images.env"
{
  echo "# LOCAL DEVELOPMENT ONLY — NEVER PUSH TO GHCR OR MAVEN CENTRAL"
  echo "COMMON_GAV=io.github.bliplink:com.app.common:$local_version"
  echo "COMMON_JAR_SHA256=$common_digest"
  printf '%s\n' "${images[@]}"
} > "$manifest"
log "PASS: all three local images contain identical Common JAR: $common_digest"
log "Manifest: $manifest"
log "These images have NOT been deployed to the live dc-saas containers."
