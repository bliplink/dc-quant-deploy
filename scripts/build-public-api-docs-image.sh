#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${PUBLIC_API_DOCS_TAG:-local/opentradingcore-api-docs:sha-$(git -C "$ROOT" rev-parse --short=12 HEAD)}"
BASE_REF="${PUBLIC_API_DOCS_BASE_REF:-}"
if [[ -z "$BASE_REF" ]] && git -C "$ROOT" rev-parse --verify origin/saas-crypto >/dev/null 2>&1; then
  BASE_REF=origin/saas-crypto
fi
check_args=()
if [[ -n "$BASE_REF" ]]; then
  check_args=(--base-ref "$BASE_REF")
fi
python3 "$ROOT/scripts/check-public-api-docs-i18n.py" "${check_args[@]}"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/otc-public-api-docs.XXXXXX")"
cleanup() {
  if [[ -d "$STAGING" && "$STAGING" == */otc-public-api-docs.* ]]; then
    rm -r -- "$STAGING"
  fi
}
trap cleanup EXIT

"$ROOT/scripts/prepare-public-api-docs-context.sh" "$STAGING"

docker build \
  --build-arg "PYTHON_IMAGE=${PUBLIC_API_DOCS_PYTHON_IMAGE:-docker.m.daocloud.io/library/python:3.12-slim}" \
  --build-arg "NGINX_IMAGE=${PUBLIC_API_DOCS_NGINX_IMAGE:-nginx:1.27-alpine}" \
  --file "$ROOT/docs/public-api/Dockerfile" --tag "$TAG" "$STAGING"
printf '[public-api-docs] built %s\n' "$TAG"
