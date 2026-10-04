#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${ROOT}/.env.prod}"
LOCK_FILE="${2:-${ROOT}/release/saas-crypto-images.env}"

[[ -f "$ENV_FILE" ]] || { echo "[release-lock] env file not found: $ENV_FILE" >&2; exit 1; }
[[ -f "$LOCK_FILE" ]] || { echo "[release-lock] lock file not found: $LOCK_FILE" >&2; exit 1; }

count=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  case "$line" in ''|'#'*) continue ;; esac
  [[ "$line" == *=* ]] || { echo "[release-lock] invalid line: $line" >&2; exit 1; }
  key="${line%%=*}"
  value="${line#*=}"
  case "$key" in
    IMAGE_SOURCE|REQUIRE_GHCR_LOGIN|*_IMAGE_REPOSITORY|*_TAG) ;;
    *) echo "[release-lock] unexpected key in lock: $key" >&2; exit 1 ;;
  esac
  "${SCRIPT_DIR}/upsert-env-value.sh" "$ENV_FILE" "$key" "$value"
  count=$((count + 1))
done < "$LOCK_FILE"

echo "[release-lock] applied ${count} locked image settings to ${ENV_FILE}"
