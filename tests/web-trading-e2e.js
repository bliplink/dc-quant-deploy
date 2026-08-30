const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const password = process.env.E2E_PASSWORD;
const buyer = process.env.E2E_BUYER || 'webbuyer';
const seller = process.env.E2E_SELLER || 'webseller';
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';
const ignoredConsoleErrors = [
  // TradingView rejects late historical bars after a newer snapshot; this does
  // not affect the authenticated order, execution, balance, or recent-trade flow.
  /^time order violation, prev:/
];

if (!password) {
  throw new Error('E2E_PASSWORD is required');
}

fs.mkdirSync(artifactDir, { recursive: true });

function requestMethod(response) {
  try {
    const body = response.request().postDataJSON();
    return body && (body.method || (body.content && body.content.method));
  } catch (error) {
    return '';
  }
}

async function invokeFromPage(page, method, action) {
  const [response] = await Promise.all([
    page.waitForResponse(
      candidate => candidate.url().includes('/httpapi/') && requestMethod(candidate) === method,
      { timeout: 60000 }
    ),
    action()
  ]);
  const body = await response.json();
  if (Number(body.code) !== 0) {
    throw new Error(`${method} failed: ${JSON.stringify(body)}`);
  }
  return body;
}

async function login(browser, username) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {
    const consoleText = message.text();
    if (message.type() === 'error' && !ignoredConsoleErrors.some(pattern => pattern.test(consoleText))) {
      pageErrors.push(`console: ${consoleText}`);
    }
  });

  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
    waitUntil: 'domcontentloaded'
  });
  await page.waitForTimeout(3000);
  const inputs = page.locator('.loginWrap input');
  const inputCount = await inputs.count();
  if (inputCount < 2) {
    await page.screenshot({
      path: path.join(artifactDir, `login-render-failure-${username}.png`),
      fullPage: true
    });
    const bodyText = await page.locator('body').innerText().catch(() => '');
    throw new Error(`login form did not render: ${JSON.stringify({
      url: page.url(),
      title: await page.title(),
      inputCount,
      bodyText: bodyText.slice(0, 1000),
      pageErrors
    })}`);
  }
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  const loginBody = await invokeFromPage(page, 'SYS.ATS.LOGIN', () =>
    page.locator('.loginWrap .ant-btn-primary').click()
  );
  if (loginBody.data.user_id !== username) {
    throw new Error(`login returned unexpected user ${loginBody.data.user_id}`);
  }
  if (loginBody.data.location !== location) {
    throw new Error(`login returned unexpected location ${loginBody.data.location}`);
  }
  await page.waitForFunction(() => Boolean(sessionStorage.getItem('loginData')));
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
  await page.locator('.tradeWrap').waitFor({ timeout: 60000 });
  await page.waitForTimeout(3000);
  return { context, page, pageErrors };
}

async function deposit(page, amount) {
  await page.locator('.accountInfoWrap').getByText('Deposit', { exact: true }).click();
  const modal = page.locator('.ant-modal:visible').filter({ hasText: 'Deposit' });
  await modal.locator('input').fill(String(amount));
  await invokeFromPage(page, 'cashIn', () =>
    modal.getByRole('button', { name: 'Confirm Deposit' }).click()
  );
  await page.waitForTimeout(1500);
}

async function placeLimit(page, side, price, amount) {
  const form = page.locator('.placeOrderWrap');
  await form.getByRole('button', { name: 'Limit', exact: true }).click();
  const priceInput = form.getByRole('textbox', { name: 'Limit Price', exact: true });
  const amountInput = form.getByRole('textbox', { name: 'Amount', exact: true });
  if (await priceInput.count() !== 1 || await amountInput.count() !== 1) {
    throw new Error(
      `expected one limit-price and one amount input, got price=${await priceInput.count()} amount=${await amountInput.count()}`
    );
  }
  await priceInput.fill(String(price));
  await amountInput.fill(String(amount));
  return invokeFromPage(page, 'placeOrder', () =>
    form.getByRole('button', { name: side }).click()
  );
}

async function openOrders(page) {
  // The live order book continuously relayouts this section. Force the tab
  // click after resolving the exact visible control so Playwright does not
  // spend its action timeout waiting for a permanently "stable" bounding box.
  await page.locator('.orderWrap').getByText('Open Orders', { exact: true }).click({ force: true });
  return page
    .locator('.orderWrap .ant-tabs-tabpane-active .openOrderWrap .ant-table-tbody tr')
    .filter({ hasText: 'BTCUSDT' });
}

async function cancelFirstOpenOrder(page) {
  const rows = await openOrders(page);
  await rows.first().waitFor({ timeout: 15000 });
  await invokeFromPage(page, 'cancelOrder', () =>
    rows.first().getByText('Cancel', { exact: true }).click()
  );
  await page.waitForTimeout(1200);
}

async function waitForRestingBid(page, expectedPrice) {
  const bid = page.locator('.orderBookWrap .showDiv .bid-price').filter({hasText: String(expectedPrice)}).first();
  try {
    await bid.waitFor({timeout: 20000});
  } catch (error) {
    const diagnostics = await page.evaluate(() => ({
      currentSymbol: sessionStorage.getItem('currentSymbol'),
      loginData: sessionStorage.getItem('loginData'),
      orderBookText: document.querySelector('.orderBookWrap')?.innerText || '',
      bidPrices: [...document.querySelectorAll('.orderBookWrap .bid-price')].map(item => item.textContent),
      askPrices: [...document.querySelectorAll('.orderBookWrap .ask-price')].map(item => item.textContent)
    }));
    throw new Error(`resting bid did not reach Web order book: ${JSON.stringify(diagnostics)}`);
  }
  const row = bid.locator('xpath=..');
  const text = await row.innerText();
  if (!text.includes(String(expectedPrice))) {
    throw new Error(`resting bid is missing from the Web order book: ${text}`);
  }
  return text;
}

async function waitForMarketMetric(page, label) {
  const metric = page.locator('.symbolMarketWrap > .df.fdc').filter({
    has: page.getByText(label, {exact: true})
  }).first();
  await metric.waitFor({timeout: 20000});
  await page.waitForFunction(
    ({selector, text}) => {
      const nodes = [...document.querySelectorAll(selector)];
      const node = nodes.find(item => item.innerText.includes(text));
      return node && !node.innerText.includes('--') && /\d/.test(node.innerText);
    },
    {selector: '.symbolMarketWrap > .df.fdc', text: label},
    {timeout: 20000}
  );
  return metric.innerText();
}

async function verifyKlineAndMarketData(page) {
  // MDSvr deliberately batches ClickHouse writes.  The realtime K-line is
  // already sent over WebSocket, but a reload can race the asynchronous
  // history insert.  Poll the real browser history request until the same
  // tenant bar is durable instead of accepting a transient empty response.
  const deadline = Date.now() + 60000;
  let klineBody = null;
  let klineRows = [];
  do {
    const klineResponsePromise = page.waitForResponse(
      response => response.url().includes('/httpapi/') && requestMethod(response) === 'queryKLine',
      {timeout: 60000}
    );
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.locator('.tradeWrap').waitFor({timeout: 60000});
    const klineResponse = await klineResponsePromise;
    klineBody = await klineResponse.json();
    if (Number(klineBody.code) !== 0) {
      throw new Error(`queryKLine failed: ${JSON.stringify(klineBody)}`);
    }
    klineRows = Array.isArray(klineBody.data)
      ? klineBody.data
      : (klineBody.data && Array.isArray(klineBody.data.data) ? klineBody.data.data : []);
    if (klineRows.length) break;
    await page.waitForTimeout(2000);
  } while (Date.now() < deadline);
  if (!klineRows.length) {
    throw new Error(`queryKLine returned no durable tenant bars within 60s: ${JSON.stringify(klineBody)}`);
  }
  await page.locator('.TVChartContainer iframe').waitFor({timeout: 30000});
  const lastPrice = await waitForMarketMetric(page, 'Last Price');
  const markPrice = await waitForMarketMetric(page, 'Mark Price');
  const indexPrice = await waitForMarketMetric(page, 'Index Price');
  return {klineRows: klineRows.length, lastPrice, markPrice, indexPrice};
}

async function clearOpenOrders(page) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const rows = await openOrders(page);
    if (await rows.count() === 0) return;
    await invokeFromPage(page, 'cancelOrder', () =>
      rows.first().getByText('Cancel', { exact: true }).click()
    );
    await page.waitForTimeout(500);
  }
  throw new Error('failed to clear existing E2E open orders');
}

async function tradeHistoryText(page) {
  await page.locator('.orderWrap').getByText('Trade History', { exact: true }).click({ force: true });
  // Tabs are force-rendered, so inactive tables stay in the DOM as hidden rows.
  // Scope the lookup to the active pane instead of taking the first global row.
  const row = page
    .locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
    .filter({ hasText: 'BTCUSDT' })
    .filter({ hasText: '60000' })
    .filter({ hasText: '0.001' })
    .first();
  await row.waitFor({ timeout: 20000 });
  return row.innerText();
}

async function recentTradeText(page, expectedTime) {
  await page.getByText('Recent Trades', { exact: true }).click();
  const row = page.locator('.recentTradeDiv.showDiv .bid').filter({ hasText: '60000' }).first();
  await row.waitFor({ timeout: 20000 });
  const deadline = Date.now() + 20000;
  let text = '';
  do {
    text = await row.innerText();
    if (!expectedTime || text.includes(expectedTime)) return text;
    await page.waitForTimeout(250);
  } while (Date.now() < deadline);
  throw new Error(`recent trade did not advance to ${expectedTime}: ${text}`);
}

async function positionRows(page, side) {
  await page.locator('.orderWrap').getByText('Positions', { exact: true }).click({ force: true });
  let rows = page
    .locator('.orderWrap .ant-tabs-tabpane-active .orderPositionWrap .ant-table-tbody tr')
    .filter({ hasText: 'BTCUSDT' });
  if (side) rows = rows.filter({ hasText: side });
  return rows;
}

async function closeFirstPosition(page, side) {
  const rows = await positionRows(page, side);
  await rows.first().waitFor({ timeout: 15000 });
  await invokeFromPage(page, 'placeOrder', () =>
    rows.first().getByText('Close', { exact: true }).click()
  );
}

async function waitForNoPosition(page) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await (await positionRows(page)).count() === 0) return;
    await page.waitForTimeout(500);
  }
  throw new Error('position did not close after the offsetting execution');
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  let buyerSession;
  let sellerSession;
  try {
    buyerSession = await login(browser, buyer);
    sellerSession = await login(browser, seller);

    await clearOpenOrders(buyerSession.page);
    await clearOpenOrders(sellerSession.page);

    await deposit(buyerSession.page, '100000');
    await deposit(sellerSession.page, '100000');

    await placeLimit(buyerSession.page, 'Buy / Long', '10000', '0.001');
    const restingBid = await waitForRestingBid(buyerSession.page, '10000');
    await cancelFirstOpenOrder(buyerSession.page);

    await placeLimit(buyerSession.page, 'Buy / Long', '60000', '0.001');
    await (await openOrders(buyerSession.page)).first().waitFor({ timeout: 15000 });
    await placeLimit(sellerSession.page, 'Sell / Short', '60000', '0.001');

    const buyerTrade = await tradeHistoryText(buyerSession.page);
    const sellerTrade = await tradeHistoryText(sellerSession.page);
    const buyerTradeTime = (buyerTrade.match(/\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}:\d{2})/) || [])[1];
    const recentTrade = await recentTradeText(buyerSession.page, buyerTradeTime);
    if (!buyerTradeTime || !recentTrade.includes(buyerTradeTime)) {
      throw new Error(`recent trade is stale: execution=${buyerTrade} recent=${recentTrade}`);
    }
    const marketData = await verifyKlineAndMarketData(buyerSession.page);
    await buyerSession.page.screenshot({
      path: path.join(artifactDir, 'web-market-data.png'),
      fullPage: true
    });

    // Rest an offsetting buy for the short account, then exercise the Web
    // reduce-only Market/IOC close action for the long account. The same match
    // closes both sides and leaves the acceptance location flat.
    await placeLimit(sellerSession.page, 'Buy / Long', '60000', '0.001');
    await (await openOrders(sellerSession.page)).first().waitFor({ timeout: 15000 });
    await closeFirstPosition(buyerSession.page, 'Long');
    await waitForNoPosition(buyerSession.page);
    await waitForNoPosition(sellerSession.page);

    await buyerSession.page.screenshot({
      path: path.join(artifactDir, 'buyer-trading-flow.png'),
      fullPage: true
    });
    await sellerSession.page.screenshot({
      path: path.join(artifactDir, 'seller-trade-history.png'),
      fullPage: true
    });

    if (buyerSession.pageErrors.length || sellerSession.pageErrors.length) {
      throw new Error(`page errors: ${JSON.stringify({
        buyer: buyerSession.pageErrors,
        seller: sellerSession.pageErrors
      })}`);
    }

    console.log(JSON.stringify({
      status: 'PASS',
      location,
      login: [buyer, seller],
      deposit: 'PASS',
      cancel: 'PASS',
      execution: 'PASS',
      closePosition: 'PASS',
      buyerTrade,
      sellerTrade,
      recentTrade,
      marketData: {
        orderBook: restingBid,
        recentTrade,
        ...marketData
      }
    }, null, 2));
  } catch (error) {
    if (buyerSession) {
      await buyerSession.page.screenshot({
        path: path.join(artifactDir, 'buyer-trading-flow-failure.png'),
        fullPage: true
      }).catch(() => {});
    }
    if (sellerSession) {
      await sellerSession.page.screenshot({
        path: path.join(artifactDir, 'seller-trading-flow-failure.png'),
        fullPage: true
      }).catch(() => {});
    }
    throw error;
  } finally {
    if (buyerSession) await buyerSession.context.close();
    if (sellerSession) await sellerSession.context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
