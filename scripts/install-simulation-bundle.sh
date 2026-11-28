#!/usr/bin/env bash
# Installed as install.sh next to the verified release images.
set -euo pipefail
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: ./install.sh TRUSTED_MANIFEST_SHA256 [PRIVATE_STATE_DIRECTORY]'
  exit 0
fi
if [[ $# -lt 1 || $# -gt 2 || ! "$1" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'Supply the 64-character SHA-256 printed in the release record.' >&2
  exit 2
fi
release="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$release/deployment/scripts/install-public-simulation.py" \
  --state-dir "${2:-$HOME/.opentradingcore/simulation}" \
  --image-bundle "$release" --bundle-sha256 "$1"
