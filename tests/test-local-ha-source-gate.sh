#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$ROOT/scripts/build-local-ha-demo.sh"
bash -n "$script"

# Exercise the EXACT source gate function without starting Docker builds.
eval "$(sed -n '/^require_committed_source() {/,/^}/p' "$script")"
[[ "$(type -t require_committed_source)" == "function" ]] || {
  echo 'source gate not found' >&2; exit 1;
}
fail() { echo "expected source-gate refusal: $*" >&2; exit 2; }

temp="$(mktemp -d)"
trap 'rm -rf -- "$temp"' EXIT
git -C "$temp" init -q
git -C "$temp" -c user.name=Test -c user.email=test@invalid.local   commit --allow-empty -qm 'test initial'
echo committed > "$temp/pom.xml"
git -C "$temp" add pom.xml
git -C "$temp" -c user.name=Test -c user.email=test@invalid.local commit -qm 'commit source'
require_committed_source "$temp"

mkdir -p "$temp/target/classes"
echo generated > "$temp/target/classes/Generated.class"
require_committed_source "$temp" # Maven output does not change source provenance

echo dirty >> "$temp/pom.xml"
if (require_committed_source "$temp" 2>/dev/null); then
  echo 'uncommitted tracked changes were allowed' >&2; exit 1
fi
git -C "$temp" restore pom.xml

echo untracked > "$temp/NewSource.java"
if (require_committed_source "$temp" 2>/dev/null); then
  echo 'untracked source was allowed' >&2; exit 1
fi
rm "$temp/NewSource.java"

echo staged >> "$temp/pom.xml"
git -C "$temp" add pom.xml
if (require_committed_source "$temp" 2>/dev/null); then
  echo 'staged but not committed source was allowed' >&2; exit 1
fi
git -C "$temp" restore --staged pom.xml
git -C "$temp" restore pom.xml

require_committed_source "$temp"
echo '[local-ha-source-gate-test] PASS'
