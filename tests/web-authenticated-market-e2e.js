'use strict';

const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const username = process.env.E2E_USER || 'webbuyer';
const password = process.env.E2E_PASSWORD;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';
const browserExecutable = process.env.E2E_BROWSER_EXECUTABLE;

if (!password) throw new Error('E2E_PASSWORD is required');
fs.mkdirSync(artifactDir, {recursive: true});

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(browserExecutable ? {executablePath: browserExecutable} : {})
  });
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  const page = await context.newPage();
  const pageErrors = [];
  const publicMarketPollingCalls = [];

  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') pageErrors.push(`console: ${message.text()}`);
  });
  page.on('request', request => {
    if (!request.url().includes('/httpapi/')) return;
    try {
      const body = request.postDataJSON();
      if (body && body.method === 'queryPublicMarket') publicMarketPollingCalls.push(body);
    } catch (_) {}
  });

  try {
    await page.addInitScript(() => {
      if (window === window.top) sessionStorage.clear();
    });
    await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
      waitUntil: 'domcontentloaded'
    });
    const inputs = page.locator('.loginWrap input');
    await inputs.nth(0).fill(username);
    await inputs.nth(1).fill(password);
    await page.locator('.loginWrap .ant-btn-primary').click();
    await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
    await page.locator('.tradeWrap').waitFor({timeout: 60000});
    await page.waitForFunction(() => Boolean(sessionStorage.getItem('loginData')), null, {timeout: 60000});

    const loginData = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loginData') || '{}'));
    if (loginData.user_id !== username || loginData.location !== location || !loginData.token) {
      throw new Error(`invalid websocket login session: ${JSON.stringify(loginData)}`);
    }

    await page.waitForFunction(() => {
      const orderBook = [...document.querySelectorAll('.orderBookWrap')].find(element => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
      });
      const asks = orderBook?.querySelectorAll('.showDiv .ask-container > .bid').length || 0;
      const bids = orderBook?.querySelectorAll('.showDiv .ask-container + div + div > .bid').length || 0;
      return bids === 10 && asks === 10;
    }, null, {timeout: 60000});

    try {
      await page.waitForFunction(() => {
        const realtime = window.__dcRealtimeKlineStatus;
        return realtime && realtime.updates >= 2
          && Date.now() - realtime.receivedAt < 15000;
      }, null, {timeout: 60000});
    } catch (error) {
      const frameStatus = await Promise.all(page.frames().map(async frame => ({
        url: frame.url(),
        status: await frame.evaluate(() => ({
          history: window.__dcKlineStatus || null,
          realtime: window.__dcRealtimeKlineStatus || null
        })).catch(frameError => ({error: frameError.message}))
      })));
      await page.screenshot({
        path: path.join(artifactDir, 'web-authenticated-market-failure.png'),
        fullPage: true
      });
      throw new Error(`authenticated K-line did not update: ${JSON.stringify({frameStatus, pageErrors})}`);
    }

    const evidence = await page.evaluate(() => {
      const orderBook = [...document.querySelectorAll('.orderBookWrap')].find(element => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
      });
      return {
        history: window.__dcKlineStatus,
        realtime: window.__dcRealtimeKlineStatus,
        bids: orderBook?.querySelectorAll('.showDiv .ask-container + div + div > .bid').length || 0,
        asks: orderBook?.querySelectorAll('.showDiv .ask-container > .bid').length || 0,
        lastPrice: orderBook?.querySelector('.showDiv .last-price')?.textContent?.trim() || ''
      };
    });
    if (!evidence.realtime.topic.endsWith(`.${location}`)
      || evidence.realtime.symbol !== 'BTCUSDT'
      || evidence.realtime.time > Date.now() + 5 * 60 * 1000) {
      throw new Error(`invalid authenticated realtime K-line: ${JSON.stringify(evidence.realtime)}`);
    }
    if (publicMarketPollingCalls.length) {
      throw new Error(`authenticated market used polling: ${JSON.stringify(publicMarketPollingCalls)}`);
    }
    if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);

    const screenshot = path.join(artifactDir, 'web-authenticated-market.png');
    await page.screenshot({path: screenshot, fullPage: true});
    process.stdout.write(`${JSON.stringify({
      status: 'PASS',
      location,
      username,
      websocketLogin: true,
      publicMarketPollingCalls: 0,
      ...evidence,
      screenshot
    }, null, 2)}\n`);
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
