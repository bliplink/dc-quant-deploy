#!/usr/bin/env bash
# Build candidate JVM images against one copy of each pinned shared library.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:?usage: build-public-simulation-core.sh OUTPUT_DIRECTORY}"
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"
work="$(mktemp -d "$dest/.core-XXXXXXXX")"
trap 'rm -rf "$work"' EXIT
for module in gateway-api common shared order trade market-data gateway; do
  mkdir "$work/$module"
  git -C "$root/sources/$module" archive "$(git -C "$root" rev-parse "HEAD:sources/$module")" | tar -x -C "$work/$module"
done
build=(mvn -B -ntp "-Dmaven.repo.local=$work/m2" -Dmaven.test.skip=true -Dproject.build.outputTimestamp=2000-01-01T00:00:00Z)
for module in gateway-api/gateway-api-java/gateway-api common shared; do
  "${build[@]}" -f "$work/$module/pom.xml" install
done
common=("$work"/common/target/com.app.common-*.jar)
shared=("$work"/shared/target/com.app.dc-*.jar)
test "${#common[@]}" = 1
test "${#shared[@]}" = 1
common_sha="$(shasum -a 256 "${common[0]}" | cut -d' ' -f1)"
common_ref="$(git -C "$root" rev-parse HEAD:sources/common)"
# Run the existing two-direction physical crash gate against the JAR packaged below.
candidate="$work/qualification-input"
mkdir "$candidate"
cp "${common[0]}" "$candidate/common-tested-class-bytes.jar"
printf '%s\n' "$common_ref" > "$candidate/commit.sha"
(cd "$work/common" && { find src -type f -print0; printf 'pom.xml\0'; } |
  LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$candidate/source.sha256"
mvn -B -ntp "-Dmaven.repo.local=$work/m2" -f "$work/common/pom.xml" -DskipTests test-compile dependency:build-classpath
if ! MAC_DEMO_COMMON_SOURCE="$root/sources/common" MAC_DEMO_MAVEN="$(command -v mvn)" \
    MAC_DEMO_REQUIRE_INTERRUPTED_RETURN=true MAVEN_ARGS="${MAVEN_ARGS:-} -Dmaven.repo.local=$work/m2" \
    bash "$root/scripts/verify-mac-common-failover.sh" "$candidate" "$common_sha" "$work/fault-results" \
    > "$work/fault-gate.log" 2>&1; then
  echo "Common physical crash qualification failed for $common_sha" >&2
  grep -E 'PHYSICAL_P0_CASE_FAILED|^FAIL |^ValueError:|^Common fixture build failed' "$work/fault-gate.log" | tail -8 >&2 || true
  exit 1
fi
test "$(cat "$work/fault-results/status")" = PASS
echo "Common physical fault qualification passed: $common_sha"
for module in order trade market-data gateway; do
  src="$work/$module"
  "${build[@]}" -f "$src/pom.xml" package dependency:copy-dependencies \
    -DincludeScope=runtime "-DoutputDirectory=$src/target/dependency"
  if [[ "$module" == order ]]; then
    javac -cp "$src/target/dependency/*" -d "$src/target/classes" \
      "$root/scripts/java/T554ProtectedNamespaceInstaller.java" \
      "$root/scripts/java/T530OriginalE1DualPhysicalGenesisSeal.java"
  fi
  packaged_common=("$src"/target/dependency/com.app.common-*.jar)
  packaged_shared=("$src"/target/dependency/com.app.dc-[0-9]*.jar)
  test "${#packaged_common[@]}" = 1
  cmp "${common[0]}" "${packaged_common[0]}"
  test "${#packaged_shared[@]}" = 1
  cmp "${shared[0]}" "${packaged_shared[0]}"
  pin="$(git -C "$root" rev-parse "HEAD:sources/$module")"
  archive="$work/$module.oci.tar"
  docker buildx build --platform linux/amd64,linux/arm64 --build-arg "SERVICE_REVISION=$pin" \
    --build-arg "COMMON_REVISION=$common_ref" --build-arg "COMMON_JAR_SHA256=$common_sha" \
    --build-arg "COMMON_GAV=io.github.bliplink:$(basename "${common[0]}" .jar | sed 's/^com.app.common-/com.app.common:/')" \
    --label "org.opencontainers.image.revision=$pin" --label "dc.common.jar.sha256=$common_sha" \
    --tag "otc-simulation/$module:$pin" --output "type=oci,dest=$archive" "$src"
  python3 "$root/scripts/verify-simulation-oci.py" "$archive" "$pin"
  mv "$archive" "$dest/$module-$pin.oci.tar"
done
