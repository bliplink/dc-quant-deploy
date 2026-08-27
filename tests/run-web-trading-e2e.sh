#!/usr/bin/env bash
set -euo pipefail

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

cd "${work_dir}"
npm init -y >/dev/null
npm install --no-audit --no-fund --silent playwright@1.55.0

NODE_PATH="${work_dir}/node_modules" node /work/web-trading-e2e.js
