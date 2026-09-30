'use strict';

const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION;
const password = process.env.E2E_PASSWORD;
const user = process.env.E2E_USER || 'tenantadmin';
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';
const browserExecutable = process.env.E2E_BROWSER_EXECUTABLE;

if (!location || !password) throw new Error('E2E_LOCATION and E2E_PASSWORD are required');
fs.mkdirSync(artifactDir, {recursive: true});

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(browserExecutable ? {executablePath: browserExecutable} : {})
  });
  const page = await browser.newPage({viewport: {width: 1280, height: 800}});
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    await page.addInitScript(() => {
      if (window === window.top) sessionStorage.clear();
    });
    await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
      waitUntil: 'domcontentloaded'
    });
    const inputs = page.locator('.loginWrap input');
    await inputs.nth(0).fill(user);
    await inputs.nth(1).fill(password);
    await page.locator('.loginWrap .ant-btn-primary').click();
    await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
    await page.locator('.tradeWrap').waitFor({timeout: 60000});
    await page.waitForFunction(() => {
      const book = [...document.querySelectorAll('.orderBookWrap')].find(element => {
        const bounds = element.getBoundingClientRect();
        return bounds.width > 0 && bounds.height > 0;
      });
      const bids = book?.querySelectorAll('.showDiv .ask-container + div + div > .bid').length || 0;
      const asks = book?.querySelectorAll('.showDiv .ask-container > .bid').length || 0;
      return bids >= 3 && asks >= 3;
    }, null, {timeout: 60000});
    const evidence = await page.evaluate(() => {
      const book = [...document.querySelectorAll('.orderBookWrap')].find(element => {
        const bounds = element.getBoundingClientRect();
        return bounds.width > 0 && bounds.height > 0;
      });
      const bids = [...book.querySelectorAll('.showDiv .ask-container + div + div > .bid')];
      const asks = [...book.querySelectorAll('.showDiv .ask-container > .bid')];
      return {
        bids: bids.length,
        asks: asks.length,
        bidSample: bids[0]?.innerText?.trim().slice(0, 120),
        askSample: asks[0]?.innerText?.trim().slice(0, 120),
        location: JSON.parse(sessionStorage.getItem('loginData') || '{}').location
      };
    });
    if (evidence.location !== location) throw new Error(`wrong tenant location: ${evidence.location}`);
    if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);
    const screenshot = path.join(artifactDir, `trial-liquidity-${location}.png`);
    await page.screenshot({path: screenshot, fullPage: true});
    process.stdout.write(`${JSON.stringify({status: 'PASS', ...evidence, screenshot})}\n`);
  } finally {
    await browser.close();
  }
})().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
