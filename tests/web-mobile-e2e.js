const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const username = process.env.E2E_USER || 'webbuyer';
const password = process.env.E2E_PASSWORD;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';

if (!password) throw new Error('E2E_PASSWORD is required');
fs.mkdirSync(artifactDir, {recursive: true});

async function login(page) {
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
    waitUntil: 'domcontentloaded'
  });
  const loginBox = await page.locator('.loginWrap').boundingBox();
  if (!loginBox || loginBox.x < 0 || loginBox.x + loginBox.width > 390) {
    throw new Error(`mobile login form overflows viewport: ${JSON.stringify(loginBox)}`);
  }
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();
  await page.waitForFunction(() => Boolean(sessionStorage.getItem('loginData')));
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
  await page.locator('.tradeGrid').waitFor({timeout: 60000});
  const body = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loginData') || '{}'));
  if (Number(body.code) !== 0 || body.user_id !== username || body.location !== location) {
    throw new Error(`websocket login failed: ${JSON.stringify(body)}`);
  }
  await page.waitForTimeout(2500);
}

async function viewportMetrics(page) {
  return page.evaluate(() => {
    const panelBoxes = [...document.querySelectorAll('.tradePanel')].map((panel) => {
      const rect = panel.getBoundingClientRect();
      return {left: rect.left, right: rect.right, width: rect.width, top: rect.top};
    });
    const button = document.querySelector('.orderBuyBtn');
    const amount = document.querySelector('[aria-label="Amount"]');
    const header = document.querySelector('.headerWrap');
    const symbol = document.querySelector('.symbolMarket');
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      panelBoxes,
      panelCount: panelBoxes.length,
      dragHandleCount: document.querySelectorAll('.panelDragHandle').length,
      header: header ? header.getBoundingClientRect().toJSON() : null,
      symbol: symbol ? symbol.getBoundingClientRect().toJSON() : null,
      buyButtonHeight: button ? button.getBoundingClientRect().height : 0,
      amountInputHeight: amount ? amount.getBoundingClientRect().height : 0
    };
  });
}

function assertResponsive(metrics, viewportWidth) {
  if (metrics.documentWidth > viewportWidth + 1 || metrics.bodyWidth > viewportWidth + 1) {
    throw new Error(`page has horizontal overflow: ${JSON.stringify(metrics)}`);
  }
  if (metrics.panelCount !== 5) throw new Error(`expected five panels: ${JSON.stringify(metrics)}`);
  const outside = metrics.panelBoxes.filter(box => box.left < -1 || box.right > viewportWidth + 1);
  if (outside.length) throw new Error(`panels overflow viewport: ${JSON.stringify(outside)}`);
  for (let index = 1; index < metrics.panelBoxes.length; index += 1) {
    if (metrics.panelBoxes[index].top <= metrics.panelBoxes[index - 1].top) {
      throw new Error(`mobile panels are not vertically stacked: ${JSON.stringify(metrics.panelBoxes)}`);
    }
  }
  if (!metrics.header || metrics.header.left < -1 || metrics.header.right > viewportWidth + 1) {
    throw new Error(`header overflows viewport: ${JSON.stringify(metrics.header)}`);
  }
  if (!metrics.symbol || metrics.symbol.left < -1 || metrics.symbol.right > viewportWidth + 1) {
    throw new Error(`market summary overflows viewport: ${JSON.stringify(metrics.symbol)}`);
  }
  if (metrics.buyButtonHeight < 40 || metrics.amountInputHeight < 36) {
    throw new Error(`order controls are not touch friendly: ${JSON.stringify(metrics)}`);
  }
  if (metrics.dragHandleCount !== 0) {
    throw new Error('mobile auto-layout must not expose accidental drag handles');
  }
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({
    viewport: {width: 390, height: 844},
    deviceScaleFactor: 1,
    hasTouch: true,
    isMobile: true
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await login(page);
    await page.locator('.languageSwitch button').nth(1).tap();
    await page.getByText('Last Price', {exact: true}).first().waitFor({timeout: 10000});

    const metrics = await viewportMetrics(page);
    assertResponsive(metrics, 390);

    await page.locator('.symbolDiv').tap();
    const drawer = page.locator('.ant-drawer');
    await drawer.getByPlaceholder('Search markets').waitFor({timeout: 10000});
    const drawerBox = await drawer.boundingBox();
    if (!drawerBox || drawerBox.left < -1 || drawerBox.right > 391) {
      throw new Error(`market drawer overflows mobile viewport: ${JSON.stringify(drawerBox)}`);
    }
    await drawer.getByPlaceholder('Search markets').fill('BTC');
    await drawer.getByText('BTCUSDT', {exact: true}).tap();
    await drawer.waitFor({state: 'hidden', timeout: 10000});

    const placeOrder = page.locator('.placeOrderWrap');
    await placeOrder.scrollIntoViewIfNeeded();
    await page.getByRole('button', {name: 'Market', exact: true}).tap();
    await page.getByLabel('Amount').fill('0.001');
    if (!(await page.getByRole('button', {name: 'Buy / Long'}).isVisible())) {
      throw new Error('mobile order action is not reachable');
    }

    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-en.png'), fullPage: true});
    await page.locator('.languageSwitch button').nth(0).tap();
    await page.getByText('订单簿', {exact: true}).first().waitFor({timeout: 10000});
    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-zh.png'), fullPage: true});

    if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);
    console.log(JSON.stringify({
      status: 'PASS',
      location,
      viewport: '390x844',
      noHorizontalOverflow: true,
      verticallyStackedPanels: 5,
      touchFriendlyOrderEntry: true,
      responsiveMarketDrawer: true,
      mobileAutoLayout: true,
      languages: ['en', 'zh'],
      artifacts: ['workspace-mobile-en.png', 'workspace-mobile-zh.png']
    }, null, 2));
  } catch (error) {
    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-failure.png'), fullPage: true}).catch(() => {});
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
