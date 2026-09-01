'use strict';

const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';
const browserExecutable = process.env.E2E_BROWSER_EXECUTABLE;

fs.mkdirSync(artifactDir, {recursive: true});

function fail(message, details) {
  throw new Error(`${message}${details === undefined ? '' : `: ${JSON.stringify(details)}`}`);
}

function timeout(ms, message) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms));
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(browserExecutable ? {executablePath: browserExecutable} : {})
  });
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  const page = await context.newPage();
  const pageErrors = [];
  const klineResponses = [];
  const publicMarketResponses = [];

  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') pageErrors.push(`console: ${message.text()}`);
  });
  page.on('response', async response => {
    if (!response.url().includes('/httpapi/')) return;
    let requestBody;
    try { requestBody = response.request().postDataJSON(); } catch (_) { return; }
    if (!requestBody) return;
    try {
      const body = await response.json();
      if (requestBody.method === 'queryPublicMarket') {
        const entries = body.data?.orderBook?.NoMDEntries || [];
        publicMarketResponses.push({
          code: Number(body.code),
          bids: entries.filter(item => String(item.MDEntryType) === '0').length,
          asks: entries.filter(item => String(item.MDEntryType) === '1').length
        });
        return;
      }
      if (requestBody.method !== 'queryKLine') return;
      const rows = Array.isArray(body.data)
        ? body.data
        : (body.data && Array.isArray(body.data.data) ? body.data.data : []);
      klineResponses.push({
        code: Number(body.code),
        rows: rows.length,
        request: requestBody.content,
        first: rows[0] || null,
        last: rows[rows.length - 1] || null
      });
    } catch (error) {
      klineResponses.push({code: -1, rows: 0, error: error.message});
    }
  });

  try {
    await page.addInitScript(() => {
      // Playwright also injects this script into TradingView's iframe. Do not
      // let the child frame erase the top-level tenant market state after the
      // application has selected its default symbol.
      if (window === window.top) {
        window.sessionStorage.clear();
        window.localStorage.setItem('dc-trade-language', 'en');
      }
    });
    await page.goto(`${baseUrl}/#/trade?location=${encodeURIComponent(location)}`, {
      waitUntil: 'domcontentloaded'
    });
    try {
      await page.locator('.tradeWrap').waitFor({timeout: 60000});
    } catch (error) {
      const diagnostics = {
        url: page.url(),
        title: await page.title(),
        body: (await page.locator('body').innerText().catch(() => '')).slice(0, 2000),
        pageErrors
      };
      await page.screenshot({path: path.join(artifactDir, 'web-public-render-failure.png'), fullPage: true});
      fail('public trade page did not render', diagnostics);
    }

    if (page.url().includes('/login')) fail('anonymous market page redirected to login', page.url());
    const session = await page.evaluate(() => ({
      token: sessionStorage.getItem('ff-dex-token'),
      loginData: sessionStorage.getItem('loginData')
    }));
    if (session.token || session.loginData) fail('anonymous market page created an authenticated session', session);

    await page.locator('.publicActions').waitFor({state: 'visible', timeout: 15000});
    const navItems = await page.locator('.head-user .navItem').allInnerTexts();
    if (!navItems.includes('Trade') || !navItems.includes('Apply')) fail('public navigation is incomplete', navItems);
    if (navItems.includes('Tenant Admin') || navItems.includes('Derivatives')) {
      fail('public user can see a restricted navigation item', navItems);
    }

    const loginPanels = page.locator('.loginRequiredPanel');
    if (await loginPanels.count() !== 2) fail('private account panels are not protected', await loginPanels.count());
    for (let index = 0; index < 2; index += 1) {
      await loginPanels.nth(index).waitFor({state: 'visible', timeout: 15000});
    }
    const publicOrderActions = page.locator('.placeOrderWrap.publicMode .publicOrderActions');
    await publicOrderActions.waitFor({state: 'visible', timeout: 15000});
    if (await publicOrderActions.locator('button').count() !== 2) {
      fail('public order panel does not expose register and login actions');
    }

    try {
      await page.waitForFunction(() => {
        const wrappers = [...document.querySelectorAll('.orderBookWrap')].filter(element => {
          const style = window.getComputedStyle(element);
          const box = element.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
        });
        const orderBook = wrappers[0];
        const asks = orderBook?.querySelectorAll('.showDiv .ask-container > .bid').length || 0;
        const bids = orderBook?.querySelectorAll('.showDiv .ask-container + div + div > .bid').length || 0;
        const lastPrice = orderBook?.querySelector('.showDiv .last-price')?.textContent?.trim() || '';
        return bids === 10 && asks === 10 && lastPrice && lastPrice !== '--';
      }, null, {timeout: 60000});
    } catch (error) {
      const diagnostics = await page.evaluate(() => ({
        url: location.href,
        locationQuery: new URLSearchParams(location.hash.split('?')[1] || '').get('location'),
        orderBooks: [...document.querySelectorAll('.orderBookWrap')].map(element => ({
          text: element.innerText.slice(0, 1500),
          bids: element.querySelectorAll('.showDiv .ask-container + div + div > .bid').length,
          asks: element.querySelectorAll('.showDiv .ask-container > .bid').length,
          width: element.getBoundingClientRect().width,
          height: element.getBoundingClientRect().height
        }))
      }));
      await page.screenshot({path: path.join(artifactDir, 'web-public-market-failure.png'), fullPage: true});
      fail('anonymous order book did not become ready', {diagnostics, publicMarketResponses, pageErrors});
    }
    if (publicMarketResponses.length) {
      fail('anonymous market page used polling snapshot API instead of MDSvr websocket subscriptions',
        publicMarketResponses);
    }

    const market = await page.evaluate(() => {
      const wrappers = [...document.querySelectorAll('.orderBookWrap')].filter(element => {
        const style = window.getComputedStyle(element);
        const box = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
      });
      const orderBook = wrappers[0];
      const rowView = element => {
        if (!element) return null;
        const row = element.getBoundingClientRect();
        const container = element.parentElement?.getBoundingClientRect();
        const visibleHeight = container
          ? Math.max(0, Math.min(row.bottom, container.bottom) - Math.max(row.top, container.top))
          : 0;
        return {
          text: element.innerText,
          width: row.width,
          height: row.height,
          containerHeight: container?.height || 0,
          visibleHeight,
          display: getComputedStyle(element).display,
          visibility: getComputedStyle(element).visibility,
          opacity: getComputedStyle(element).opacity
        };
      };
      const depthView = selector => [...(orderBook?.querySelectorAll(selector) || [])].map(element => {
        const row = element.getBoundingClientRect();
        const depth = getComputedStyle(element, '::before');
        return {
          rowWidth: row.width,
          barWidth: Number.parseFloat(depth.width) || 0,
          color: depth.backgroundColor,
          transition: depth.transitionDuration
        };
      });
      return {
        bids: orderBook?.querySelectorAll('.showDiv .ask-container + div + div > .bid').length || 0,
        asks: orderBook?.querySelectorAll('.showDiv .ask-container > .bid').length || 0,
        lastPrice: orderBook?.querySelector('.showDiv .last-price')?.textContent?.trim() || '',
        bidSample: rowView(orderBook?.querySelector('.showDiv .ask-container + div + div > .bid')),
        askSample: rowView(orderBook?.querySelector('.showDiv .ask-container > .bid')),
        bidDepth: depthView('.showDiv .ask-container + div + div > .order-book-row--bid'),
        askDepth: depthView('.showDiv .ask-container > .order-book-row--ask')
      };
    });
    if (!market.bidSample || !market.askSample
      || market.bidSample.containerHeight < 100 || market.askSample.containerHeight < 100
      || market.bidSample.visibleHeight < 10 || market.askSample.visibleHeight < 10) {
      fail('order book rows exist but are not visibly laid out', market);
    }
    for (const [side, bars] of [['bid', market.bidDepth], ['ask', market.askDepth]]) {
      const rowWidth = bars[0]?.rowWidth || 0;
      const maxBarWidth = Math.max(0, ...bars.map(item => item.barWidth));
      if (bars.length !== 10 || bars.some(item => item.barWidth <= 0 || item.barWidth > item.rowWidth + 1)
        || maxBarWidth < rowWidth * 0.95 || bars.some(item => item.transition === '0s')) {
        fail(`${side} cumulative depth bars are not visibly scaled and animated`, bars);
      }
    }
    if (market.bidDepth[0].color === market.askDepth[0].color) {
      fail('bid and ask cumulative depth bars do not use distinct colors', market);
    }
    const depthScreenshot = path.join(artifactDir, 'web-order-book-depth.png');
    await page.screenshot({path: depthScreenshot, fullPage: true});

    await page.locator('.TVChartContainer iframe').waitFor({state: 'visible', timeout: 60000});
    const history = await Promise.race([
      (async () => {
        for (let attempt = 0; attempt < 120; attempt += 1) {
          const result = klineResponses.find(item => item.code === 0 && item.rows > 1);
          if (result) return result;
          await page.waitForTimeout(250);
        }
        return null;
      })(),
      timeout(35000, 'timed out waiting for chart history')
    ]);
    if (!history) {
      await page.screenshot({path: path.join(artifactDir, 'web-public-history-failure.png'), fullPage: true});
      fail('the first chart load did not request durable K-line history', {
        klineResponses,
        publicMarketResponses,
        pageErrors
      });
    }
    await page.waitForFunction(() => window.__dcKlineStatus && window.__dcKlineStatus.receivedRows > 1, null, {timeout: 10000});
    const chartHistory = await page.evaluate(() => window.__dcKlineStatus);
    if (chartHistory.bars <= 1 || chartHistory.lastTime > Date.now() + 5 * 60 * 1000) {
      fail('K-line history was returned but not normalized into renderable bars', chartHistory);
    }
    await page.waitForTimeout(3000);
    const chartFrame = page.frames().find(frame => frame !== page.mainFrame());
    const chartRender = chartFrame ? {
      text: (await chartFrame.locator('body').innerText()).slice(0, 1000),
      canvases: await chartFrame.locator('canvas').count()
    } : null;
    if (!chartRender || chartRender.canvases < 1 || !/O\d+(?:\.\d+)?H\d+(?:\.\d+)?L\d+(?:\.\d+)?C\d+(?:\.\d+)?/.test(chartRender.text)) {
      fail('TradingView loaded history but did not paint OHLC candles', chartRender);
    }

    await page.waitForFunction(() => {
      const status = window.__dcRealtimeKlineStatus;
      return status && status.updates >= 2 && Date.now() - status.receivedAt < 15000;
    }, null, {timeout: 45000});
    const realtimeKline = await page.evaluate(() => window.__dcRealtimeKlineStatus);
    if (!realtimeKline.topic.endsWith(`.${location}`)
      || realtimeKline.symbol !== 'BTCUSDT'
      || realtimeKline.time > Date.now() + 5 * 60 * 1000) {
      fail('MDSvr realtime K-line push has an invalid tenant, symbol or timestamp', realtimeKline);
    }

    const dragZones = page.locator('.panelDragZone');
    if (await dragZones.count() < 5) fail('desktop panels do not expose drag zones', await dragZones.count());
    await dragZones.first().hover();
    await page.waitForTimeout(250);
    const dragAffordance = await dragZones.first().evaluate(element => ({
      cursor: getComputedStyle(element).cursor,
      markerOpacity: getComputedStyle(element, '::before').opacity,
      markerContent: getComputedStyle(element, '::before').content
    }));
    if (dragAffordance.cursor !== 'move' || Number(dragAffordance.markerOpacity) < 0.9) {
      fail('hover drag affordance is not active', dragAffordance);
    }
    await page.locator('.layoutResetButton').waitFor({state: 'visible', timeout: 10000});

    const screenshot = path.join(artifactDir, 'web-public-market.png');
    await page.screenshot({path: screenshot, fullPage: true});

    await page.locator('.publicActions .primary').click();
    await page.waitForURL(`**/#/register?location=${encodeURIComponent(location)}`, {timeout: 15000});
    const tenantContext = await page.locator('.tenant-route-context').innerText();
    if (!tenantContext.includes(location)) fail('registration page did not inherit tenant from URL', tenantContext);
    if (await page.locator('.tenant-route-context input').count() !== 0) {
      fail('registration page allows the tenant to be edited');
    }

    if (pageErrors.length) fail('public market page raised runtime errors', pageErrors);
    process.stdout.write(`${JSON.stringify({
      status: 'PASS', location, market, historyRows: history.rows, historyRequest: history.request,
      chartHistory, chartCanvases: chartRender.canvases,
      realtimeKline,
      navItems, protectedPanels: 2, publicOrderActions: 2, publicMarketPollingCalls: 0, depthScreenshot,
      dragAffordance, registrationTenant: location, screenshot
    }, null, 2)}\n`);
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
