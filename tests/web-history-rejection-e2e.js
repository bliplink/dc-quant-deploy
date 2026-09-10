const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const password = process.env.E2E_PASSWORD;
const historyLocation = process.env.E2E_HISTORY_LOCATION || 'WEB_WS_E2E';
const historyUser = process.env.E2E_HISTORY_USER || 'webbuyerws';
const rejectionLocation = process.env.E2E_REJECTION_LOCATION || 'WEB_E2E';
const rejectionUser = process.env.E2E_REJECTION_USER || 'webbuyer';
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';

if (!password) throw new Error('E2E_PASSWORD is required');
fs.mkdirSync(artifactDir, {recursive: true});

async function login(browser, username, location) {
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  const page = await context.newPage();
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
    waitUntil: 'domcontentloaded'
  });
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();
  await page.waitForFunction(() => Boolean(sessionStorage.getItem('loginData')));
  await page.locator('.tradeWrap').waitFor({timeout: 60000});
  return {context, page};
}

async function historyRow(page, tabName) {
  const tab = page.locator('.orderWrap .ant-tabs-tab').filter({hasText: tabName}).first();
  await tab.evaluate(node => node.click());
  await page.waitForFunction(name => [...document.querySelectorAll('.orderWrap .ant-tabs-tab')]
    .some(node => node.classList.contains('ant-tabs-tab-active') && node.textContent.trim() === name), tabName);
  const pane = page.locator('.orderWrap .ant-tabs-tabpane-active');
  const row = pane.locator('.ant-table-tbody tr')
    .filter({hasText: 'BTCUSDT'})
    .filter({hasText: '60000'})
    .filter({hasText: '0.001'})
    .first();
  try {
    await row.waitFor({timeout: 35000});
  } catch (error) {
    const diagnostics = await page.evaluate(() => ({
      url: location.href,
      loginData: sessionStorage.getItem('loginData'),
      tabs: [...document.querySelectorAll('.orderWrap .ant-tabs-tab')].map(node => ({
        className: node.className,
        text: node.textContent
      })),
      activePane: document.querySelector('.orderWrap .ant-tabs-tabpane-active')?.innerText || '',
      messages: [...document.querySelectorAll('.ant-message-notice, .ant-notification-notice')]
        .map(node => node.textContent)
    }));
    throw new Error(`history row not visible: ${JSON.stringify(diagnostics)}`);
  }
  return row.innerText();
}

async function verifyDurableHistory(browser) {
  const session = await login(browser, historyUser, historyLocation);
  try {
    const firstTrade = await historyRow(session.page, 'Trade History');
    const firstOrder = await historyRow(session.page, 'Order History');
    await session.page.reload({waitUntil: 'domcontentloaded'});
    await session.page.locator('.tradeWrap').waitFor({timeout: 60000});
    const reloadedTrade = await historyRow(session.page, 'Trade History');
    await session.page.screenshot({
      path: path.join(artifactDir, 'web-durable-history.png'),
      fullPage: true
    });
    return {firstTrade, firstOrder, reloadedTrade};
  } finally {
    await session.context.close();
  }
}

async function verifyRejectedOrderNotification(browser) {
  const session = await login(browser, rejectionUser, rejectionLocation);
  try {
    const form = session.page.locator('.placeOrderWrap');
    await form.getByRole('button', {name: 'Limit', exact: true}).click();
    await form.getByRole('textbox', {name: 'Limit Price', exact: true}).fill('90000');
    await form.getByRole('textbox', {name: 'Amount', exact: true}).fill('0.001');
    await form.getByRole('combobox', {name: 'Time in Force', exact: true}).selectOption('PO');
    await form.getByRole('button', {name: 'Buy / Long', exact: true}).click();

    const notice = session.page.locator('.ant-notification-notice-error')
      .filter({hasText: 'Order rejected'})
      .filter({hasText: 'BTCUSDT'})
      .first();
    await notice.waitFor({timeout: 30000});
    const noticeText = await notice.innerText();
    if (!noticeText.includes('Post Only order would execute immediately') || !noticeText.includes('ID ')) {
      throw new Error(`rejection notification is incomplete: ${noticeText}`);
    }
    await session.page.screenshot({
      path: path.join(artifactDir, 'web-order-rejected-notification.png'),
      fullPage: true
    });
    return noticeText;
  } finally {
    await session.context.close();
  }
}

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const durableHistory = await verifyDurableHistory(browser);
    const rejectedOrderNotification = await verifyRejectedOrderNotification(browser);
    console.log(JSON.stringify({
      status: 'PASS',
      durableHistory,
      rejectedOrderNotification
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
