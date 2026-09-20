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

async function login(page, width) {
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
    waitUntil: 'domcontentloaded'
  });
  const loginBox = await page.locator('.loginWrap').boundingBox();
  if (!loginBox || loginBox.x < -1 || loginBox.x + loginBox.width > width + 1) {
    throw new Error(`mobile login form overflows viewport: ${JSON.stringify(loginBox)}`);
  }

  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();

  await page.waitForFunction(() => {
    try {
      const login = JSON.parse(sessionStorage.getItem('loginData') || '{}');
      return Boolean(login.user_id && login.location);
    } catch (_) {
      return false;
    }
  }, {timeout: 20000});
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
  await page.locator('.mobileWorkspaceBar').waitFor({state: 'visible', timeout: 60000});
  await page.waitForFunction(() => {
    const price = document.querySelector('.symbolMarketWrap strong');
    return price && price.textContent && !price.textContent.includes('--');
  }, {timeout: 30000});

  const body = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loginData') || '{}'));
  const authenticatedUsername = body.user_name || body.user_id;
  if (Number(body.code) !== 0 || authenticatedUsername !== username || !body.user_id || body.location !== location) {
    throw new Error(`websocket login failed: ${JSON.stringify(body)}`);
  }
  await page.waitForTimeout(1200);
}

async function viewportMetrics(page) {
  return page.evaluate(() => {
    const rect = selector => {
      const node = document.querySelector(selector);
      return node ? node.getBoundingClientRect().toJSON() : null;
    };
    const isVisible = selector => {
      const node = document.querySelector(selector);
      return Boolean(node && getComputedStyle(node).display !== 'none' && node.getBoundingClientRect().width > 0);
    };
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      header: rect('.headerWrap'),
      symbol: rect('.symbolMarket'),
      workspaceBar: rect('.mobileWorkspaceBar'),
      workspaceTabs: document.querySelectorAll('.mobileWorkspaceTabs button').length,
      lowerTabs: document.querySelectorAll('.mobileLowerTabs button').length,
      chartWorkspaceVisible: isVisible('.mobileTradeWorkspace.workspace-chart'),
      orderWorkspaceVisible: isVisible('.mobileTradeWorkspace.workspace-order'),
      mobileTradeBarVisible: isVisible('.mobileTradeBar'),
      desktopMainVisible: isVisible('.mainBody'),
      dragHandleCount: document.querySelectorAll('.panelDragZone').length
    };
  });
}

function assertWithinViewport(box, width, label) {
  if (!box || box.left < -1 || box.right > width + 1) {
    throw new Error(`${label} overflows viewport: ${JSON.stringify(box)}`);
  }
}

function assertPortrait(metrics) {
  if (metrics.documentWidth > 391 || metrics.bodyWidth > 391) {
    throw new Error(`portrait page has horizontal overflow: ${JSON.stringify(metrics)}`);
  }
  if (metrics.workspaceTabs !== 2 || metrics.lowerTabs !== 2) {
    throw new Error(`expected Chart/Order and Positions/Orders tabs: ${JSON.stringify(metrics)}`);
  }
  if (!metrics.chartWorkspaceVisible || metrics.orderWorkspaceVisible || !metrics.mobileTradeBarVisible) {
    throw new Error(`portrait must open in Chart workspace with fixed trade actions: ${JSON.stringify(metrics)}`);
  }
  if (metrics.desktopMainVisible) throw new Error('desktop grid is visible in portrait mobile workspace');
  assertWithinViewport(metrics.header, 390, 'header');
  assertWithinViewport(metrics.symbol, 390, 'market summary');
  assertWithinViewport(metrics.workspaceBar, 390, 'workspace bar');
}

async function verifyMarketDrawer(page, width) {
  await page.locator('.symbolDiv').tap();
  const search = page.locator('.marketSearch input');
  await search.waitFor({state: 'visible', timeout: 10000});
  const drawer = page.locator('.ant-drawer-content-wrapper').filter({has: page.locator('.marketSearch')});
  const drawerBox = await drawer.boundingBox();
  assertWithinViewport(drawerBox, width, 'market drawer');
  await search.fill('BTC');
  await page.getByText('BTCUSDT', {exact: true}).last().tap();
  await search.waitFor({state: 'hidden', timeout: 10000});
}

async function verifyAccountDrawer(page, width, height) {
  await page.locator('.mobileAccountTrigger').tap();
  const drawer = page.locator('.mobileAccountDrawer .ant-drawer-content-wrapper');
  await drawer.waitFor({state: 'visible', timeout: 10000});
  const box = await drawer.boundingBox();
  assertWithinViewport(box, width, 'account drawer');
  if (!box || box.height > height * 0.85) {
    throw new Error(`account drawer is too tall: ${JSON.stringify(box)}`);
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
}

async function verifyOrderWorkspace(page, width, landscape = false) {
  const buy = page.locator('.mobileTradeBar .buy');
  await buy.waitFor({state: 'visible', timeout: 10000});
  const buyBox = await buy.boundingBox();
  if (!buyBox || buyBox.height < (landscape ? 32 : 40)) {
    throw new Error(`mobile buy launcher is not touch reachable: ${JSON.stringify(buyBox)}`);
  }
  await buy.tap();

  const split = page.locator('.mobileOrderSplit');
  await split.waitFor({state: 'visible', timeout: 10000});
  const entry = page.locator('.mobileOrderEntry .placeOrderWrap');
  const book = page.locator('.mobileOrderBook .orderBookWrap');
  await entry.waitFor({state: 'visible', timeout: 10000});
  await book.waitFor({state: 'visible', timeout: 10000});

  const splitBox = await split.boundingBox();
  const entryBox = await page.locator('.mobileOrderEntry').boundingBox();
  const bookBox = await page.locator('.mobileOrderBook').boundingBox();
  assertWithinViewport(splitBox, width, 'order split');
  if (!entryBox || !bookBox || entryBox.width < width * 0.40 || bookBox.width < width * 0.35) {
    throw new Error(`order entry/book split is unusable: ${JSON.stringify({entryBox, bookBox})}`);
  }

  await entry.getByRole('button', {name: 'Market', exact: true}).tap();
  const amount = entry.getByLabel('Amount');
  await amount.fill('0.001');
  const amountBox = await amount.boundingBox();
  const orderBuy = entry.locator('.orderBuyBtn');
  const orderBuyBox = await orderBuy.boundingBox();
  if (!amountBox || amountBox.height < (landscape ? 26 : 30) || !orderBuyBox || orderBuyBox.height < 30) {
    throw new Error(`order controls are not touch reachable: ${JSON.stringify({amountBox, orderBuyBox})}`);
  }

  await page.waitForFunction(() => document.querySelectorAll('.mobileOrderBook .order-book-row').length >= 10, {timeout: 15000});

  if (landscape) {
    const optionsBox = await entry.locator('.orderOptionsGrid').boundingBox();
    const actionsBox = await entry.locator('.orderActionBar').boundingBox();
    if (optionsBox && actionsBox && optionsBox.bottom > actionsBox.top + 1) {
      throw new Error(`landscape order options overlap actions: ${JSON.stringify({optionsBox, actionsBox})}`);
    }
  }
}

async function verifyPortrait(browser) {
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
    await login(page, 390);
    await page.locator('.languageSwitch select').selectOption('en');
    await page.getByRole('button', {name: 'Chart', exact: true}).waitFor({timeout: 10000});

    const metrics = await viewportMetrics(page);
    assertPortrait(metrics);

    const profile = page.locator('.profileSummary');
    const profileBox = await profile.boundingBox();
    if (!profileBox || profileBox.width < 26 || profileBox.height < 26) {
      throw new Error(`mobile profile control is not touch reachable: ${JSON.stringify(profileBox)}`);
    }
    await profile.tap();
    const logout = page.locator('.logoutButton');
    await logout.waitFor({state: 'visible', timeout: 10000});
    const logoutBox = await logout.boundingBox();
    if (!logoutBox || logoutBox.height < 28) {
      throw new Error(`mobile sign-out control is not touch reachable: ${JSON.stringify(logoutBox)}`);
    }
    await profile.tap();

    const lowerTabs = page.locator('.mobileLowerTabs button');
    await lowerTabs.nth(0).tap();
    await page.locator('.compactPosition').waitFor({state: 'visible', timeout: 10000});
    await lowerTabs.nth(1).tap();
    await page.locator('.compactOpenOrders').waitFor({state: 'visible', timeout: 10000});
    await lowerTabs.nth(0).tap();

    await verifyMarketDrawer(page, 390);
    await verifyAccountDrawer(page, 390, 844);
    await verifyOrderWorkspace(page, 390, false);

    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-order-en.png'), fullPage: false});

    await page.locator('.mobileWorkspaceTabs button').first().tap();
    await page.locator('.languageSwitch select').selectOption('zh');
    await page.getByRole('button', {name: '图表', exact: true}).waitFor({timeout: 10000});
    await page.getByRole('button', {name: '交易', exact: true}).waitFor({timeout: 10000});
    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-chart-zh.png'), fullPage: false});

    if (pageErrors.length) throw new Error(`portrait page errors: ${JSON.stringify(pageErrors)}`);
  } finally {
    await context.close();
  }
}

async function verifyLandscape(browser) {
  const context = await browser.newContext({
    viewport: {width: 844, height: 390},
    deviceScaleFactor: 1,
    hasTouch: true,
    isMobile: true
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await login(page, 844);
    await page.locator('.languageSwitch select').selectOption('en');
    const metrics = await viewportMetrics(page);
    if (metrics.documentWidth > 845 || metrics.bodyWidth > 845 || metrics.workspaceTabs !== 2 ||
        !metrics.chartWorkspaceVisible || metrics.desktopMainVisible || !metrics.mobileTradeBarVisible) {
      throw new Error(`landscape did not enter mobile workspace cleanly: ${JSON.stringify(metrics)}`);
    }
    assertWithinViewport(metrics.header, 844, 'landscape header');
    assertWithinViewport(metrics.symbol, 844, 'landscape market summary');

    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-landscape-chart.png'), fullPage: false});
    await verifyOrderWorkspace(page, 844, true);
    await page.screenshot({path: path.join(artifactDir, 'workspace-mobile-landscape-order.png'), fullPage: false});

    if (pageErrors.length) throw new Error(`landscape page errors: ${JSON.stringify(pageErrors)}`);
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    await verifyPortrait(browser);
    await verifyLandscape(browser);
    console.log(JSON.stringify({
      status: 'PASS',
      location,
      portrait: '390x844',
      landscape: '844x390',
      workspaces: ['Chart', 'Order'],
      lowerTabs: ['Positions', 'Orders'],
      combinedOrderEntryAndBook: true,
      accountBottomSheet: true,
      noHorizontalOverflow: true,
      touchFriendlyOrderEntry: true,
      responsiveMarketDrawer: true,
      languages: ['en', 'zh'],
      artifacts: [
        'workspace-mobile-order-en.png',
        'workspace-mobile-chart-zh.png',
        'workspace-mobile-landscape-chart.png',
        'workspace-mobile-landscape-order.png'
      ]
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
