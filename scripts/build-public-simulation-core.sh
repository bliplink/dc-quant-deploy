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
