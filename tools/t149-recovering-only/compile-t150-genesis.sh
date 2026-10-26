#!/usr/bin/env bash
# Recompile the T150 lab-only Genesis reader for one real Order/Trade dependency set.
# Does NOT run signing, touch a service, publish READY, or copy artifacts to Docker.
set -euo pipefail
if [ "$#" -ne 3 ] || { [ "$1" != "order" ] && [ "$1" != "trade" ]; }; then
  echo "Usage: bash compile-t150-genesis.sh order|trade <T145/T148-target-dependency-dir> <output-dir>" >&2
  exit 2
fi
service="$1"
deps="$2"
out="$3"
script_dir="$(cd "$(dirname "$0")" && pwd)"
expected="9197029483a8d18032de0a8ca2f8888a9e62d8933b8cf8d4604206e246ca60ea"
if [ ! -d "$deps" ]; then echo "T150_FAIL: missing exact service runtime dependency directory" >&2; exit 1; fi
common_jar=""
count=0
for file in "$deps"/com.app.common-*t143*.jar; do
  [ -f "$file" ] || continue
  common_jar="$file"
  count=$((count+1))
done
if [ "$count" != 1 ]; then echo "T150_FAIL: exactly one Common T143 binary required" >&2; exit 1; fi
actual="$(shasum -a 256 "$common_jar" | awk '{print $1}')"
if [ "$actual" != "$expected" ]; then
  echo "T150_FAIL: unpinned Common binary SHA256 mismatch" >&2
  exit 1
fi
mkdir -p "$out"
javac -source 8 -target 8 -cp "$deps/*" -d "$out" \
  "$script_dir/bootstrap/T150RealEmptyBusinessGenesis.java"
major="$(javap -verbose -classpath "$out" T150RealEmptyBusinessGenesis | awk '/major version:/ {print $3;exit}')"
if [ "$major" != 52 ]; then
  echo "T150_FAIL: genesis helper is not Java 8 compatible" >&2
  exit 1
fi
echo "T150_LAB_GENESIS_SOURCE_COMPILE_PASS service=$service commonSha256=$actual javaMajor=$major"
echo "T150_NO_READY_NO_DEPLOY: helper compiles only; runtime candidate remains RECOVERING"