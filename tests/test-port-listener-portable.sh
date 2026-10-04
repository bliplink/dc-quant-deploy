#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROBE="${ROOT}/scripts/port-is-listening.sh"
port=54321
if "$PROBE" "$port"; then
  echo "test port ${port} is already occupied" >&2
  exit 1
fi
python3 -m http.server "$port" --bind 127.0.0.1 >/dev/null 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  if "$PROBE" "$port"; then
    echo '[port-listener] PASS: portable listener probe detected a real TCP listener'
    exit 0
  fi
  sleep 0.1
done
echo "listener probe failed to detect test server on ${port}" >&2
exit 1
