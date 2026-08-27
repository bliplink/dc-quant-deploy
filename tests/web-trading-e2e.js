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
  const responsePromise = page.waitForResponse(
    response => response.url().includes('/httpapi/') && requestMethod(response) === method,
    { timeout: 20000 }
  );
  await action();
  const response = await responsePromise;
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
    page.locator('.loginWrap button').click()
  );
  if (loginBody.data.user_id !== username) {
    throw new Error(`login returned unexpected user ${loginBody.data.user_id}`);
  }
  if (loginBody.data.location !== location) {
    throw new Error(`login returned unexpected location ${loginBody.data.location}`);
  }
  await page.waitForFunction(() => Boolean(sessionStorage.getItem('loginData')));
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
  await page.locator('.tradeWrap').waitFor({ timeout: 20000 });
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
  const inputs = form.locator('input:visible');
  if (await inputs.count() !== 2) {
    throw new Error(`expected two visible limit-order inputs, got ${await inputs.count()}`);
  }
  await inputs.nth(0).fill(String(price));
  await inputs.nth(1).fill(String(amount));
  return invokeFromPage(page, 'placeOrder', () =>
    form.getByRole('button', { name: side }).click()
  );
}

async function openOrders(page) {
  await page.getByText('Open Orders', { exact: true }).click();
  return page.locator('.openOrderWrap .ant-table-tbody tr').filter({ hasText: 'BTCUSDT' });
}

async function cancelFirstOpenOrder(page) {
  const rows = await openOrders(page);
  await rows.first().waitFor({ timeout: 15000 });
  await invokeFromPage(page, 'cancelOrder', () =>
    rows.first().getByText('Cancel', { exact: true }).click()
  );
  await page.waitForTimeout(1200);
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
  await page.getByText('Trade History', { exact: true }).click();
  // Tabs are force-rendered, so inactive tables stay in the DOM as hidden rows.
  // Scope the lookup to the active pane instead of taking the first global row.
  const row = page
    .locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
    .filter({ hasText: 'BTCUSDT' })
    .filter({ hasText: '60000.0' })
    .filter({ hasText: '0.0010' })
    .first();
  await row.waitFor({ timeout: 20000 });
  return row.innerText();
}

async function recentTradeText(page) {
  await page.getByText('Recent Trades', { exact: true }).click();
  const row = page.locator('.recentTradeDiv.showDiv .bid').filter({ hasText: '60000' }).first();
  await row.waitFor({ timeout: 20000 });
  return row.innerText();
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

    await placeLimit(buyerSession.page, 'Buy/Long', '10000', '0.001');
    await cancelFirstOpenOrder(buyerSession.page);

    await placeLimit(buyerSession.page, 'Buy/Long', '60000', '0.001');
    await (await openOrders(buyerSession.page)).first().waitFor({ timeout: 15000 });
    await placeLimit(sellerSession.page, 'Sell/Short', '60000', '0.001');

    const buyerTrade = await tradeHistoryText(buyerSession.page);
    const sellerTrade = await tradeHistoryText(sellerSession.page);
    const recentTrade = await recentTradeText(buyerSession.page);

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
      buyerTrade,
      sellerTrade,
      recentTrade
    }, null, 2));
  } finally {
    if (buyerSession) await buyerSession.context.close();
    if (sellerSession) await sellerSession.context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
