#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo "usage: $0 PORT" >&2; exit 2; }
port="$1"

if command -v ss >/dev/null 2>&1; then
  ss -lnt | awk 'NR > 1 {print $4}' | grep -Eq "[:.]${port}$"
elif command -v lsof >/dev/null 2>&1; then
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
elif command -v nc >/dev/null 2>&1; then
  nc -z 127.0.0.1 "${port}" >/dev/null 2>&1
else
  echo "no supported TCP listener probe found (need ss, lsof, or nc)" >&2
  exit 2
fi
