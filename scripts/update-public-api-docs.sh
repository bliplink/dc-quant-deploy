#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMAND="${1:-check}"
if [[ $# -gt 0 ]]; then shift; fi

case "$COMMAND" in
  check)
    python3 "$ROOT/scripts/check-public-api-docs-i18n.py" "$@"
    ;;
  build)
    if [[ $# -ne 0 ]]; then
      printf 'usage: %s build\n' "$0" >&2
      exit 2
    fi
    "$ROOT/scripts/build-public-api-docs-image.sh"
    ;;
  deploy)
    if [[ $# -ne 0 ]]; then
      printf 'usage: %s deploy\n' "$0" >&2
      exit 2
    fi
    if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
      printf '[public-api-docs] commit changes before deploying a sha-tagged image\n' >&2
      exit 1
    fi
    "$ROOT/scripts/build-public-api-docs-image.sh"
    "$ROOT/scripts/deploy-public-api-docs-host.sh"
    ;;
  *)
    printf 'usage: %s {check [--base-ref REF] [--accept]|build|deploy}\n' "$0" >&2
    exit 2
    ;;
esac
