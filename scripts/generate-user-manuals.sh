#!/usr/bin/env bash
# One command -> Trade, Tenant and Platform illustrated ZH/EN manuals (six PDFs).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/generate-user-manuals.py" "$@"
