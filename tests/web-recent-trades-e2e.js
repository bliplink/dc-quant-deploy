const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const username = process.env.E2E_USER || 'webbuyer';
const password = process.env.E2E_PASSWORD;

if (!password) throw new Error('E2E_PASSWORD is required');

(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
      waitUntil: 'domcontentloaded'
    });
    const inputs = page.locator('.loginWrap input');
    await inputs.nth(0).fill(username);
    await inputs.nth(1).fill(password);
    await page.locator('.loginWrap .ant-btn-primary').click();
    await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
    await page.locator('.tradeWrap').waitFor({timeout: 60000});

    const snapshot = await page.evaluate(async tenant => {
      const login = JSON.parse(sessionStorage.getItem('loginData') || '{}');
      const response = await fetch('/httpapi/', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', sessionId: login.token || login.sid || ''},
        body: JSON.stringify({
          serverName: 'MDSvr',
          method: 'queryPublicMarket',
          content: {securityID: 'BTCUSDT', location: tenant}
        })
      });
      return response.json();
    }, location);
    if (Number(snapshot.code) !== 0) {
      throw new Error(`queryPublicMarket failed: ${JSON.stringify(snapshot)}`);
    }

    const entries = snapshot.data && snapshot.data.recentTrades
      ? snapshot.data.recentTrades.NoMDEntries || []
      : [];
    const entryKey = entry => entry.MDEntryID || [
      entry.MDEntryTime,
      entry.MDEntryPx,
      entry.MDEntrySize
    ].join('|');
    const expectedUnique = Math.min(new Set(entries.map(entryKey)).size, 200);
    if (expectedUnique === 0) throw new Error('MDSvr recent-trade snapshot is empty');

    await page.getByText('Recent Trades', {exact: true}).click();
    await page.locator('.recentTradeDiv.showDiv .bid').first().waitFor({timeout: 30000});
    await page.waitForTimeout(3000);
    const rows = await page.locator('.recentTradeDiv.showDiv .bid').allTextContents();
    const actual = rows.length;
    const allowedDrift = Math.max(10, Math.ceil(expectedUnique * 0.1));
    const minimumExpected = Math.max(1, expectedUnique - allowedDrift);
    if (actual < minimumExpected || actual > 200) {
      throw new Error(
        `recent-trade snapshot mismatch: expectedUnique=${expectedUnique} ` +
        `minimum=${minimumExpected} actual=${actual}`
      );
    }
    if (new Set(rows).size !== rows.length) {
      throw new Error(`recent-trade rows contain duplicates: rendered=${rows.length} unique=${new Set(rows).size}`);
    }
    if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);

    console.log(JSON.stringify({
      status: 'PASS', location, snapshot: entries.length,
      snapshotUnique: expectedUnique, rendered: actual
    }));
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
