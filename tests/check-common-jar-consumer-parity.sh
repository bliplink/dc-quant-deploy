#!/usr/bin/env bash
# Verify that Common consumers use exactly the certified artifact already
# running in Order/Trade, rather than a stale jar bundled in a service image.
set -euo pipefail

usage() {
  echo "Usage: $0 EXPECTED_SHA256 CONTAINER ABSOLUTE_COMMON_JAR [CONTAINER ABSOLUTE_COMMON_JAR ...]" >&2
  exit 2
}
(($# >= 3)) || usage
expected="$1"
shift
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || usage
(( $# % 2 == 0 )) || usage

failures=0
while (($#)); do
  container="$1"; jar="$2"; shift 2
  if [[ "$jar" != /* ]] || [[ -z "$container" ]]; then
    echo "COMMON_CONSUMER_PARITY_INVALID_ARGUMENT"; failures=$((failures + 1)); continue
  fi
  if [[ "$(docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null || true)" != true ]]; then
    echo "COMMON_CONSUMER_NOT_RUNNING $container"; failures=$((failures + 1)); continue
  fi
  actual="$(docker exec "$container" sha256sum "$jar" 2>/dev/null | awk '{print $1}' || true)"
  if [[ "$actual" != "$expected" ]]; then
    echo "COMMON_CONSUMER_SHA_MISMATCH $container actual=${actual:-UNAVAILABLE} expected=$expected"
    failures=$((failures + 1))
  else
    echo "COMMON_CONSUMER_SHA_PASS $container sha256=$actual"
  fi
done
if ((failures)); then
  echo "COMMON_CONSUMER_PARITY_NO_GO failures=$failures" >&2
  exit 1
fi
echo "COMMON_CONSUMER_PARITY_PASS"