#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common="${MAC_DEMO_COMMON_SOURCE:-${HOME}/.opentradingcore/t525-common-latest-20261106}"
shared="${MAC_DEMO_SHARED_SOURCE:-${repo}/.work/com.app.dc}"
order="${MAC_DEMO_ORDER_SOURCE:-${repo}/.work/t545-default-exec-validation}"
trade="${MAC_DEMO_TRADE_SOURCE:-${repo}/.work/t548-tradesvr-validation}"
md="${MAC_DEMO_MD_SOURCE:-}"
maven="${MAC_DEMO_MAVEN:-${repo}/.work/t442-maven-tools/apache-maven-3.9.11/bin/mvn}"
test_rsa="${MAC_DEMO_TEST_RSA_KEYS:-${HOME}/Documents/Codex/2026-10-18/referenced-chatgpt-conversation-this-is-an/work/common-ha-netty-v19-control-cache/v19-quorum-secrets}"
verified_common="${MAC_DEMO_VERIFIED_COMMON_DIR:-}"
verified_sha="${MAC_DEMO_VERIFIED_COMMON_SHA256:-}"
verified_run="${MAC_DEMO_VERIFIED_COMMON_RESULT:-}"
common_ref="${MAC_DEMO_COMMON_REVISION:-}"
require_interrupted="${MAC_DEMO_REQUIRE_INTERRUPTED_RETURN:-false}"
projection="${MAC_DEMO_PROJECTION_HISTORY_SOURCE:-}"
gateway_base="${MAC_DEMO_GATEWAY_BASE:-}"
gateway_api="${MAC_DEMO_GATEWAY_API_SOURCE:-${repo}/.work/t407-gateway-api-readonly}"
out="${1:?usage: build-mac-demo-core.sh NEW_ABSOLUTE_ARTIFACT_DIRECTORY}"
[[ "$out" == /* && ! -e "$out" ]] || { echo "Choose a new absolute build directory" >&2; exit 2; }
[[ "$(uname -s)" == Darwin && "$(docker context show)" == colima ]] ||
  { echo "Expected the local Mac Colima context" >&2; exit 2; }
export JAVA_HOME="$(/usr/libexec/java_home -v 1.8)"
for source in "$common" "$shared" "$order" "$trade"; do
  [[ -f "$source/pom.xml" && -d "$source/src" ]]
done
if [[ -n "$md" ]]; then
  [[ -f "$md/pom.xml" && -d "$md/src" ]]
  : "${MAC_DEMO_MD_BASE:?Set MAC_DEMO_MD_BASE to the reviewed MD image}"
  docker image inspect "$MAC_DEMO_MD_BASE" --format '{{.Id}}' >/dev/null
fi
[[ -f "$test_rsa/a/node.pk8" && -f "$test_rsa/b/node.pk8" &&
   -f "$test_rsa/public/CommonHaDemoA.pub.der" && -f "$test_rsa/public/CommonHaDemoB.pub.der" ]] || {
  echo "Set MAC_DEMO_TEST_RSA_KEYS to the existing independent unit-test RSA fixture directory" >&2
  exit 2
}
if [[ -n "$verified_common" || -n "$verified_sha" || -n "$verified_run" ]]; then
  [[ "$verified_common" == /* && "$verified_run" == /* && "$verified_sha" =~ ^[a-f0-9]{64}$ && -n "$common_ref" &&
     -f "$verified_common/common-tested-class-bytes.jar" && -f "$verified_common/source.sha256" &&
     -f "$verified_common/commit.sha" ]] || {
    echo "Verified Common requires its candidate directory, fault verification result, exact SHA256 and source revision" >&2
    exit 2
  }
fi
if [[ "$require_interrupted" == true ]]; then
  [[ -n "$verified_run" ]] || { echo "An interrupted return verification result is required" >&2; exit 2; }
  python3 - "$verified_run" <<'PY_CHECK'
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
try:
    log = (root / "failover.log").read_bytes()
    seal = json.loads((root / "verification.seal.json").read_text())
    if ((root / "status").read_text().strip() != "PASS"
            or seal.get("interrupted_local_rearm") is not True
            or seal.get("transcript_sha256") != hashlib.sha256(log).hexdigest()
            or log.splitlines().count(b"T554_INTERRUPTED_LOCAL_TO_STRICT_SIGNED_STAGE_RESUMED_PASS") != 1):
        raise ValueError
except (OSError, ValueError):
    sys.exit("The exact Common result must prove interrupted signed recovery before deployment")
PY_CHECK
fi
umask 077
mkdir -p "$out"

copy_source() {
  local source="$1" destination="$2" ref="${3:-}" revision
  mkdir -p "$destination"
  if [[ -n "$ref" ]]; then
    revision="$(git -C "$source" rev-parse --verify --end-of-options "$ref^{commit}")"
    git -C "$source" archive "$revision" -- pom.xml src | tar -xf - -C "$destination"
    printf '%s\n' "$revision" > "$destination/revision"
    : > "$destination/source-status"
  else
    cp -R "$source/src" "$destination/"
    cp "$source/pom.xml" "$destination/"
    git -C "$source" rev-parse HEAD > "$destination/revision"
    git -C "$source" status --porcelain --untracked-files=no > "$destination/source-status"
  fi
  (
    cd "$destination"
    { find src -type f -print0; printf 'pom.xml\0'; } |
      LC_ALL=C sort -z | xargs -0 shasum -a 256
  ) > "$destination/source.sha256"
}

copy_source "$common" "$out/common" "$common_ref"
common_revision="$(cat "$out/common/revision")"
if [[ -n "$verified_common" ]]; then
  [[ "$common_revision" == "$(cat "$verified_common/commit.sha")" ]] &&
    cmp -s "$out/common/source.sha256" "$verified_common/source.sha256" || {
      echo "Verified Common source does not match $common_revision" >&2
      exit 2
    }
  cp "$verified_common/common-tested-class-bytes.jar" "$out/common.jar"
  common_sha="$(shasum -a 256 "$out/common.jar" | awk '{print $1}')"
  [[ "$common_sha" == "$verified_sha" ]] || {
    echo "Verified Common JAR SHA256 mismatch" >&2
    exit 2
  }
  [[ -f "$verified_run/status" && "$(cat "$verified_run/status")" == PASS &&
     -f "$verified_run/common.jar" && "$(shasum -a 256 "$verified_run/common.jar" | awk '{print $1}')" == "$common_sha" ]] &&
    rg -Fxq "common_revision=$common_revision" "$verified_run/candidate.env" &&
    rg -Fxq "common_sha256=$common_sha" "$verified_run/candidate.env" &&
    rg -q '\bT554_INDEPENDENT_AB_SIGKILL_BOTH_DIRECTIONS_256_HOME_STRICT_PASS ' "$verified_run/failover.log" &&
    rg -q '^T554_RETURNED_HOME_VOTER_THIRD_SIGKILL_REPEATED_HOME_256_PHYSICAL_MATCH_PASS$' "$verified_run/failover.log" || {
      echo "Common fault verification has not passed for this exact JAR" >&2
      exit 2
    }
else
  (cd "$out/common"; "$maven" -o -B -Dmaven.test.skip=true package) > "$out/common.log" 2>&1
  set -- "$out/common"/target/com.app.common-*.jar
  [[ "$#" == 1 && -f "$1" ]]
  cp "$1" "$out/common.jar"
  common_sha="$(shasum -a 256 "$out/common.jar" | awk '{print $1}')"
fi
copy_source "$shared" "$out/shared"
copy_source "$order" "$out/order"
copy_source "$trade" "$out/trade"
if [[ -n "$md" ]]; then copy_source "$md" "$out/md"; fi

candidate_dependencies() {
  python3 - "$@" <<'PY'
import sys
import xml.etree.ElementTree as ET
pom, common, *shared = sys.argv[1:]
ns = 'http://maven.apache.org/POM/4.0.0'
ET.register_namespace('', ns)
tree = ET.parse(pom)
deps = tree.getroot().find(f'{{{ns}}}dependencies')
if deps is None:
    raise SystemExit('Missing service dependencies')
for artifact, jar in [('com.app.common', common), *[('com.app.dc', path) for path in shared]]:
    # Keep the repository dependencies for their transitive libraries.
    # Prepend the candidate for compilation; packaging removes both old JARs.
    dep = ET.Element(f'{{{ns}}}dependency')
    for key, val in {'groupId': 'io.github.bliplink', 'artifactId': artifact + '-mac-demo-compile',
                     'version': '0.0.0-local-demo', 'scope': 'system', 'systemPath': jar}.items():
        ET.SubElement(dep, f'{{{ns}}}{key}').text = val
    deps.insert(0, dep)
tree.write(pom, encoding='UTF-8', xml_declaration=True)
PY
}

candidate_dependencies "$out/shared/pom.xml" "$out/common.jar"
(cd "$out/shared"; "$maven" -o -B "-Dotc.demo.existing.keys=$test_rsa" package) > "$out/shared.log" 2>&1
set -- "$out/shared"/target/com.app.dc-*.jar
[[ "$#" == 1 && -f "$1" ]]
cp "$1" "$out/shared.jar"
shared_sha="$(shasum -a 256 "$out/shared.jar" | awk '{print $1}')"

build_service() {
  local kind="$1" service="$2" base="$3" dependency_dir="$4"
  local src="$out/$kind" context="$out/$kind/image" service_dir="/srv/dc/dc/$service"
  local app_sha image base_id service_revision jar_hashes
  local reuse_classes=false cleanup=()
  base_id="$(docker image inspect "$base" --format '{{.Id}}')"
  [[ "$base_id" =~ ^sha256:[a-f0-9]{64}$ ]]
  base_id="$(python3 "$repo/scripts/flatten-mac-demo-build-base.py" "$base_id" \
    "${HOME}/.opentradingcore/mac-demo-flat-base-cache")"
  base="$base_id"
  service_revision="$(cat "$src/revision")"
  [[ "$service_revision" =~ ^[a-f0-9]{40}$ ]]
  candidate_dependencies "$src/pom.xml" "$out/common.jar" "$out/shared.jar"
  (cd "$src"; "$maven" -o -B "-Dotc.demo.existing.keys=$test_rsa" package) > "$out/$kind.log" 2>&1
  mkdir -p "$context/lib"
  cp "$src/target/$dependency_dir/"*.jar "$context/lib/"
  find "$context/lib" -maxdepth 1 \( -name 'com.app.common-*.jar' -o -name 'com.app.dc-*.jar' \) -delete
  # Reuse only paths whose actual image bytes match this build. Keep the
  # comparison files outside the build context.
  (
    cd "$context/lib"
    for jar in *.jar; do shasum -a 256 "$jar"; done | LC_ALL=C sort
  ) > "$src/expected-libraries.sha256"
  (
    cd "$src/target"
    find classes -type f -exec shasum -a 256 {} + | LC_ALL=C sort
  ) > "$src/expected-classes.sha256"
  if docker run --rm --network none --entrypoint sh "$base_id" -ec '
    cd "$1/lib"
    test -z "$(find . -mindepth 1 -maxdepth 1 ! -type f -print)"
    for jar in * .[!.]* ..?*; do
      test -f "$jar" || continue
      case "$jar" in
        com.app.common-mac-demo.jar|com.app.dc-mac-demo.jar) ;;
        *.jar) sha256sum "$jar" ;;
        *) exit 1 ;;
      esac
    done
    cd "$1"
    printf "\n---class-files---\n"
    test -z "$(find classes ! -type d ! -type f -print)"
    find classes -type f -exec sha256sum {} +
  ' -- "$service_dir" > "$src/base-content.unsorted" 2>"$src/base-content.log"; then
    sed '/^---class-files---$/,$d; /^$/d' "$src/base-content.unsorted" | LC_ALL=C sort > "$src/base-libraries.sha256"
    sed '1,/^---class-files---$/d' "$src/base-content.unsorted" | LC_ALL=C sort > "$src/base-classes.sha256"
  fi
  if cmp -s "$src/expected-libraries.sha256" "$src/base-libraries.sha256"; then
    find "$context/lib" -maxdepth 1 -type f -name '*.jar' -delete
  else
    cleanup+=("$service_dir/lib")
  fi
  if [[ -z "$(find "$src/target/classes" ! -type d ! -type f -print)" ]] &&
    cmp -s "$src/expected-classes.sha256" "$src/base-classes.sha256"; then
    reuse_classes=true
  else
    cleanup+=("$service_dir/classes")
    cp -R "$src/target/classes" "$context/"
  fi
  cp "$out/common.jar" "$context/lib/com.app.common-mac-demo.jar"
  cp "$out/shared.jar" "$context/lib/com.app.dc-mac-demo.jar"
  app_sha="$(shasum -a 256 "$src/source.sha256" | awk '{print $1}')"
  image="local/otc-mac-demo-$kind:${common_sha:0:12}-${shared_sha:0:12}-${app_sha:0:12}"
  {
    printf 'FROM %s\n' "$base_id"
    if [[ "${#cleanup[@]}" != 0 ]]; then
      printf 'RUN rm -rf'
      printf ' %s' "${cleanup[@]}"
      printf '\n'
    fi
    printf 'COPY lib/ %s/lib/\n' "$service_dir"
    if [[ "$reuse_classes" == false ]]; then printf 'COPY classes/ %s/classes/\n' "$service_dir"; fi
    printf 'LABEL dc.common.jar.sha256=%s dc.common.revision=%s dc.shared.jar.sha256=%s org.opencontainers.image.revision=%s dc.demo.source.sha256=%s\n' \
      "$common_sha" "$common_revision" "$shared_sha" "$service_revision" "$app_sha"
  } > "$context/Dockerfile"
  docker build -t "$image" "$context" > "$out/$kind-image.log" 2>&1
  [[ "$(docker image inspect "$base" --format '{{.Id}}')" == "$base_id" ]]
  jar_hashes="$(docker run --rm --network none --entrypoint sha256sum "$image" \
    "$service_dir/lib/com.app.common-mac-demo.jar" "$service_dir/lib/com.app.dc-mac-demo.jar" | awk '{print $1}')"
  [[ "$jar_hashes" == "$common_sha"$'\n'"$shared_sha" ]]
  printf '%s_IMAGE=%s\n' "$kind" "$image" > "$out/$kind.result"
}

build_service order OrderSvr "${MAC_DEMO_ORDER_BASE:-local/otc-t546-ordersvr:default-maven-r2}" dependency &
order_build=$!
build_service trade TradeSvr "${MAC_DEMO_TRADE_BASE:-local/otc-t548-tradesvr:maven-validation}" javalib &
trade_build=$!
status=0
wait "$order_build" || status=1
wait "$trade_build" || status=1
if [[ "$status" != 0 ]]; then
  echo "Core build failed. See $out/order.log, $out/trade.log and image logs." >&2
  exit 1
fi
if [[ -n "$md" ]]; then
  build_service md MDSvr "${MAC_DEMO_MD_BASE:?Set MAC_DEMO_MD_BASE to the reviewed MD image}" javalib
fi
if [[ -n "$projection" ]]; then
  bash "$repo/scripts/build-mac-demo-projection-history.sh" "$projection" "$out/projection"
fi
{
  printf 'common_revision=%s\ncommon_sha256=%s\n' "$common_revision" "$common_sha"
  if [[ -n "$verified_common" ]]; then
    printf 'common_fault_verification=PASS\ncommon_fault_result=%s\n' "$verified_run"
    if [[ "$require_interrupted" == true ]]; then printf 'common_interrupted_rearm_verified=true\n'; fi
  fi
  printf 'shared_revision=%s\nshared_sha256=%s\n' "$(cat "$out/shared/revision")" "$shared_sha"
  printf 'business_unit_tests=PASS\n'
  cat "$out/order.result" "$out/trade.result"
  if [[ -n "$md" ]]; then cat "$out/md.result"; fi
  if [[ -n "$projection" ]]; then cat "$out/projection/projection.env"; fi
} > "$out/images.env"
# Keep the already-qualified Gateway code; only align its exact dependencies.
# Never compile unrelated uncommitted proxy work from the Gateway checkout.
gateway_base="${gateway_base:-$(docker inspect -f '{{.Image}}' dc-saas-gateway)}"
python3 "$repo/scripts/build-mac-demo-gateway-dependencies.py" "$gateway_base" "$out" \
  "$out/gateway-dependencies" > "$out/gateway-dependencies.env"
cat "$out/gateway-dependencies.env" >> "$out/images.env"
# The notification fix is independent of Common HA and changes only one
# existing connector method. Its ABI, original dependencies and real class
# bytes are checked before all producing images are selected for deployment.
python3 "$repo/scripts/build-mac-demo-notification-fanout.py" "$out" "$gateway_api" \
  "$out/notification-release" > "$out/notification-build.log" 2>&1
cp "$out/notification-release/images.env" "$out/images.env"
cat "$out/images.env"
