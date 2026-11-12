#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common="${MAC_DEMO_COMMON_SOURCE:-${HOME}/.opentradingcore/t525-common-latest-20261106}"
maven="${MAC_DEMO_MAVEN:-${repo}/.work/t442-maven-tools/apache-maven-3.9.11/bin/mvn}"
ref="${1:?usage: build-mac-common-candidate.sh REVISION NEW_CANDIDATE_DIRECTORY [NEW_FAULT_RESULTS_DIRECTORY]}"
out="${2:?Provide a new absolute candidate directory}"
results="${3:-}"
[[ "$#" -le 3 && "$out" == /* && ! -e "$out" && "$(uname -s)" == Darwin ]] || {
  echo 'Expected the local Mac and a new absolute candidate directory' >&2
  exit 2
}
if [[ -n "$results" && ( "$results" != /* || -e "$results" || "$results" == "$out" ) ]]; then
  echo 'Provide a separate new absolute fault results directory' >&2
  exit 2
fi
revision="$(git -C "$common" rev-parse --verify --end-of-options "$ref^{commit}")"
if [[ "$ref" == HEAD && -n "$(git -C "$common" status --porcelain --untracked-files=all -- pom.xml src)" ]]; then
  echo 'Common HEAD has uncommitted source or tests. Commit the intended candidate before building HEAD.' >&2
  exit 2
fi
source_timestamp="$(git -C "$common" show -s --format=%ct "$revision")"
export JAVA_HOME="$(/usr/libexec/java_home -v 1.8)"
umask 077
mkdir -p "$(dirname "$out")"
mkdir "$out"
mkdir "$out/source"
git -C "$common" archive "$revision" -- pom.xml src | tar -xf - -C "$out/source"
(
  cd "$out/source"
  { find src -type f -print0; printf 'pom.xml\0'; } |
    LC_ALL=C sort -z | xargs -0 shasum -a 256
) > "$out/source.sha256"
if ! (cd "$out/source"; "$maven" -o -B -Dmaven.test.skip=true \
    "-Dproject.build.outputTimestamp=$source_timestamp" package) > "$out/build.log" 2>&1; then
  printf 'Common candidate build failed: %s\n' "$out/build.log" >&2
  exit 2
fi
jars=("$out/source/target/"com.app.common-*.jar)
[[ "${#jars[@]}" == 1 && -f "${jars[0]}" ]]
cp "${jars[0]}" "$out/common-tested-class-bytes.jar"
sha="$(shasum -a 256 "$out/common-tested-class-bytes.jar" | awk '{print $1}')"
printf '%s\n' "$revision" > "$out/commit.sha"
printf '%s\n' "$sha" > "$out/jar.sha"
printf 'Common candidate %s\nSHA256 %s\n' "$out" "$sha"
if [[ -n "$results" ]]; then
  MAC_DEMO_COMMON_P0_FIXTURE_REVISION="${MAC_DEMO_COMMON_P0_FIXTURE_REVISION:-$revision}" \
    bash "$repo/scripts/verify-mac-common-failover.sh" "$out" "$sha" "$results"
fi
