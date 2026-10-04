#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 3 ]] || { echo "usage: $0 ENV_FILE KEY VALUE" >&2; exit 2; }
env_file="$1"
key="$2"
value="$3"
[[ "$key" =~ ^[A-Z0-9_]+$ ]] || { echo "invalid env key: $key" >&2; exit 2; }
[[ -f "$env_file" ]] || { echo "env file not found: $env_file" >&2; exit 1; }

tmp="$(mktemp "${env_file}.tmp.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
awk -v key="$key" -v value="$value" '
BEGIN { found=0 }
$0 ~ ("^" key "=") {
  if (!found) print key "=" value
  found=1
  next
}
{ print }
END { if (!found) print key "=" value }
' "$env_file" > "$tmp"
chmod --reference="$env_file" "$tmp" 2>/dev/null || chmod 0600 "$tmp"
mv "$tmp" "$env_file"
trap - EXIT
