#!/usr/bin/env bash
# Read-only Trade Web load-sequence smoke. Does not log in or mutate tenant state.
# Usage: TRADE_WEB_LOAD_TENANTS=ABC123,DEF456 bash tests/run-trade-web-loading-smoke-host.sh
set -euo pipefail

RUNNER="${WEB_E2E_RUNNER_NAME:-dc-saas-web-e2e-runner}"
BASE="${TRADE_WEB_BASE_URL:-http://127.0.0.1:18088}"
TENANTS="${TRADE_WEB_LOAD_TENANTS:-}"
[[ -n "$TENANTS" ]] || { echo 'TRADE_WEB_LOAD_TENANTS required' >&2; exit 2; }
[[ "$TENANTS" =~ ^[A-Z0-9]{6}(,[A-Z0-9]{6}){0,4}$ ]] || {
  echo 'Supply 1–5 six-character tenant location IDs, comma-separated' >&2; exit 2;
}
[[ "$(docker inspect "$RUNNER" --format '{{.State.Status}}' 2>/dev/null)" == running ]] || {
  echo 'Playwright runner is not running' >&2; exit 2;
}
[[ "$(docker inspect "$RUNNER" --format '{{.HostConfig.NetworkMode}}')" == host ]] || {
  echo 'Playwright runner requires host network for local Trade Web' >&2; exit 2;
}

docker exec -i -e TRADE_WEB_LOAD_TENANTS="$TENANTS" -e TRADE_WEB_BASE_URL="$BASE" \
  "$RUNNER" bash -lc 'NODE_PATH=/runner/node_modules node -' <<'JS'
'use strict';
const { chromium } = require('playwright');
const tenants = process.env.TRADE_WEB_LOAD_TENANTS.split(',');
const base = process.env.TRADE_WEB_BASE_URL.replace(/\/$/, '');
const profiles = [
  { name: 'desktop', viewport: { width: 1440, height: 900 } },
  { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true },
];
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  let failures = 0;
  try {
    for (const profile of profiles) for (const location of tenants) {
      const context = await browser.newContext({ viewport: profile.viewport, isMobile: !!profile.isMobile });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(`JS ${String(error.message).slice(0, 90)}`));
      page.on('response', r => {
        if (r.status() >= 500 && errors.length < 5) errors.push(`HTTP ${r.status()}`);
      });
      const start = Date.now();
      let http = null;
      const snapshots = [];
      try {
        const response = await page.goto(`${base}/#/trade?location=${location}`, {
          waitUntil: 'domcontentloaded', timeout: 15000,
        });
        http = response.status();
        for (const at of [1500, 4500, 8500]) {
          await page.waitForTimeout(Math.max(0, at - (Date.now() - start)));
          const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
          snapshots.push({
            elapsedMs: Date.now() - start,
            symbol: text.includes('BTCUSDT'),
            noMarkets: text.includes('No markets found'),
            chartLoading: text.includes('Chart · Loading'),
          });
        }
      } catch (error) {
        errors.push(`BROWSER ${String(error.message).slice(0, 130)}`);
      }
      const last = snapshots[snapshots.length - 1];
      const ok = http === 200 && last?.symbol && !last?.noMarkets &&
        !last?.chartLoading && errors.length === 0;
      if (!ok) failures++;
      console.log(JSON.stringify({ location, viewport: profile.name, http, snapshots, errors, pass: !!ok }));
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(`TRADE_WEB_LOAD_SMOKE ${failures ? 'FAIL' : 'PASS'} cases=${profiles.length * tenants.length} failures=${failures}`);
  if (failures) process.exitCode = 1;
})().catch(error => { console.error(String(error.message)); process.exitCode = 1; });
JS
