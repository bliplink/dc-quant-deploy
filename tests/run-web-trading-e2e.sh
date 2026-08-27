#!/usr/bin/env bash
set -euo pipefail

runner_root="${E2E_RUNNER_ROOT:-/runner}"
playwright_version="1.55.0"
mkdir -p "${runner_root}"

installed_version="$(node -p "try { require('${runner_root}/node_modules/playwright/package.json').version } catch (_) { '' }" 2>/dev/null || true)"
if [[ "${installed_version}" != "${playwright_version}" ]]; then
  cd "${runner_root}"
  [[ -f package.json ]] || npm init -y >/dev/null
  npm install --no-audit --no-fund --silent "playwright@${playwright_version}"
fi

NODE_PATH="${runner_root}/node_modules" node /work/web-trading-e2e.js
