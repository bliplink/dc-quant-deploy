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
build=(mvn -B -ntp "-Dmaven.repo.local=$work/m2" -Dproject.build.outputTimestamp=2000-01-01T00:00:00Z)
for module in gateway-api/gateway-api-java/gateway-api common shared; do
  "${build[@]}" -f "$work/$module/pom.xml" -Dmaven.test.skip=true install
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
  if [[ -n "${RUNNER_TEMP:-}" && -d "$work/fault-results" ]]; then
    mkdir -p "$RUNNER_TEMP/common-diagnostics"
    # Raw test logs are sealed by CI. No identity files, WALs or private source are exported.
    tail -c 2097152 "$work/fault-gate.log" > "$RUNNER_TEMP/common-diagnostics/gate.log"
    for log in fixture-build.log failover.log native-faults.log home-faults.log; do
      if [[ -f "$work/fault-results/$log" ]]; then tail -c 2097152 "$work/fault-results/$log" > "$RUNNER_TEMP/common-diagnostics/$log"; fi
    done
  fi
  echo "Common physical crash qualification failed for $common_sha" >&2
  grep -E 'PHYSICAL_P0_CASE_FAILED|^FAIL |^ValueError:|^Common fixture build failed' "$work/fault-gate.log" | tail -8 >&2 || true
  exit 1
fi
test "$(cat "$work/fault-results/status")" = PASS
echo "Common physical fault qualification passed: $common_sha"
test_keys="$(python3 - "$root" "$work" <<'PYKEYS'
import os
from pathlib import Path
import runpy
import sys
os.umask(0o077)
helper = runpy.run_path(str(Path(sys.argv[1]) / "scripts/mac-demo-fresh.py"))
print(helper["new_demo_signers"](Path(sys.argv[2]) / "testing-keys"))
PYKEYS
)"
for module in order trade market-data gateway; do
  src="$work/$module"
  test_options=("-Dotc.demo.existing.keys=$test_keys")
  if [[ "$module" == gateway ]]; then
    test_options+=("-Ddc.gw.anonymousRoutes=$root/config/gateway-publicMethodWhitelist.csv")
  fi
  "${build[@]}" -f "$src/pom.xml" "${test_options[@]}" package dependency:copy-dependencies \
    -DincludeScope=runtime "-DoutputDirectory=$src/target/dependency"
  if [[ "$module" == order ]]; then
    javac -cp "$src/target/dependency/*" -d "$src/target/classes" \
      "$root/scripts/java/T554ProtectedNamespaceInstaller.java" \
      "$root/scripts/java/T530OriginalE1DualPhysicalGenesisSeal.java"
  fi
  # The stable connector is the runtime ABI. Carry the qualified notify method
  # from the pinned connector source, just as in the accepted Mac images.
  python3 - "$root" "$work" "$module" <<'PYBUILD'
import os
from pathlib import Path
import runpy
import shutil
import sys

root, work = map(Path, sys.argv[1:3])
module = sys.argv[3]
helper = runpy.run_path(str(root / "scripts/build-mac-demo-notification-fanout.py"))
workspace = work / ("notification-" + module)
workspace.mkdir()
target = work / module / "target"
compiled, _, _, _ = helper["compile_notification"](
    work / "gateway-api", target / "dependency", Path(os.environ["JAVA_HOME"]), workspace, work / "m2")
destination = target / "classes" / compiled.relative_to(workspace / "classes")
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(compiled, destination)
PYBUILD
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
    --label "org.opencontainers.image.revision=$pin" --label "dc.common.jar.sha256=$common_sha" --label "dc.common.p0.sha256=$common_sha" \
    --tag "otc-simulation/$module:$pin" --output "type=oci,dest=$archive" "$src"
  python3 "$root/scripts/verify-simulation-oci.py" "$archive" "$pin"
  mv "$archive" "$dest/$module-$pin.oci.tar"
done
