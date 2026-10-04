#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<'ENV'
IMAGE_SOURCE=local
MYSQL_PASSWORD=keep-me
GW_IMAGE_REPOSITORY=local/gw
GW_TAG=old
ENV
"${ROOT}/scripts/apply-release-image-lock.sh" "$tmp" "${ROOT}/release/saas-crypto-images.env" >/dev/null
grep -Fxq 'MYSQL_PASSWORD=keep-me' "$tmp"
grep -Fxq 'IMAGE_SOURCE=registry' "$tmp"
grep -Fxq 'REQUIRE_GHCR_LOGIN=true' "$tmp"
grep -Fxq 'GW_IMAGE_REPOSITORY=ghcr.io/bliplink/gw' "$tmp"
grep -Fxq 'GW_TAG=sha-6a84739' "$tmp"
! grep -Eq '=local/' "$tmp"
if command -v sha256sum >/dev/null 2>&1; then first="$(sha256sum "$tmp" | awk '{print $1}')"; else first="$(shasum -a 256 "$tmp" | awk '{print $1}')"; fi
"${ROOT}/scripts/apply-release-image-lock.sh" "$tmp" "${ROOT}/release/saas-crypto-images.env" >/dev/null
if command -v sha256sum >/dev/null 2>&1; then second="$(sha256sum "$tmp" | awk '{print $1}')"; else second="$(shasum -a 256 "$tmp" | awk '{print $1}')"; fi
[[ "$first" == "$second" ]]
echo '[release-lock-apply] PASS: image lock is safe and idempotent'
