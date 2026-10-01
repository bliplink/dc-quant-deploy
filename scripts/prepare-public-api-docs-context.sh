#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 1 || -z "$1" ]]; then
  printf 'usage: %s OUTPUT_DIRECTORY\n' "$0" >&2
  exit 2
fi
STAGING="$1"
if [[ -e "$STAGING" ]] && [[ -n "$(find "$STAGING" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  printf '[public-api-docs] output directory must be empty: %s\n' "$STAGING" >&2
  exit 1
fi

mkdir -p "$STAGING/docs/en/openapi" "$STAGING/docs/en/assets" \
  "$STAGING/docs/zh/openapi" "$STAGING/docs/zh/api" \
  "$STAGING/docs/zh/assets" "$STAGING/docs/openapi" "$STAGING/scripts"
cp "$ROOT/mkdocs.public.yml" "$ROOT/mkdocs.public.zh.yml" "$ROOT/requirements-docs.txt" "$STAGING/"
cp "$ROOT/docs/public-api/index.md" "$STAGING/docs/en/index.md"
cp "$ROOT/docs/public-api/status.md" "$STAGING/docs/en/status.md"
cp "$ROOT/docs/public-api/en/"*.md "$STAGING/docs/en/"
cp "$ROOT/docs/public-api/zh/"*.md "$STAGING/docs/zh/"
cp "$ROOT/docs/public-api/language-switch.js" "$STAGING/docs/en/assets/"
cp "$ROOT/docs/public-api/language-switch.js" "$STAGING/docs/zh/assets/"
for locale in '' en zh; do
  cp "$ROOT/docs/openapi/crypto-openapi-v1.yaml" "$STAGING/docs/${locale:+$locale/}openapi/"
done
cp "$ROOT/docs/openapi/"*.md "$STAGING/docs/zh/openapi/"
for excluded in README.zh-CN.md DEVELOPER_PORTAL_STRUCTURE.zh-CN.md EXTERNAL_GA_CHECKLIST.zh-CN.md; do
  rm -- "$STAGING/docs/zh/openapi/$excluded"
done
cp "$ROOT/docs/api/"*.md "$STAGING/docs/zh/api/"
cp "$ROOT/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" "$ROOT/docs/CRYPTO_OPEN_API_V1.zh-CN.md" "$STAGING/docs/zh/"
cp "$ROOT/scripts/validate-openapi-catalog.py" "$ROOT/scripts/generate-public-api-catalog.py" "$STAGING/scripts/"
cp "$ROOT/docs/public-api/nginx.conf" "$STAGING/nginx.conf"
