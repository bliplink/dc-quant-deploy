#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${PUBLIC_API_DOCS_TAG:-local/opentradingcore-api-docs:sha-$(git -C "$ROOT" rev-parse --short=12 HEAD)}"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/otc-public-api-docs.XXXXXX")"
cleanup() {
  if [[ -d "$STAGING" && "$STAGING" == */otc-public-api-docs.* ]]; then
    rm -r -- "$STAGING"
  fi
}
trap cleanup EXIT

mkdir -p "$STAGING/docs/openapi" "$STAGING/docs/api" "$STAGING/scripts"
cp "$ROOT/mkdocs.public.yml" "$ROOT/requirements-docs.txt" "$STAGING/"
cp "$ROOT/docs/public-api/index.md" "$STAGING/docs/index.md"
cp "$ROOT/docs/public-api/status.md" "$STAGING/docs/status.md"
cp "$ROOT/docs/openapi/"*.md "$ROOT/docs/openapi/crypto-openapi-v1.yaml" "$STAGING/docs/openapi/"
for excluded in README.zh-CN.md DEVELOPER_PORTAL_STRUCTURE.zh-CN.md EXTERNAL_GA_CHECKLIST.zh-CN.md; do
  rm -- "$STAGING/docs/openapi/$excluded"
done
cp "$ROOT/docs/api/"*.md "$STAGING/docs/api/"
cp "$ROOT/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" "$ROOT/docs/CRYPTO_OPEN_API_V1.zh-CN.md" "$STAGING/docs/"
cp "$ROOT/scripts/validate-openapi-catalog.py" "$ROOT/scripts/generate-public-api-catalog.py" "$STAGING/scripts/"
cp "$ROOT/docs/public-api/nginx.conf" "$STAGING/nginx.conf"

docker build --file "$ROOT/docs/public-api/Dockerfile" --tag "$TAG" "$STAGING"
printf '[public-api-docs] built %s\n' "$TAG"
