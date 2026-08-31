const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const username = process.env.E2E_USER || 'webbuyer';
const password = process.env.E2E_PASSWORD;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';

if (!password) throw new Error('E2E_PASSWORD is required');
fs.mkdirSync(artifactDir, {recursive: true});

async function verifyTenantRouteBinding(page) {
  await page.goto(`${baseUrl}/#/register?location=${encodeURIComponent(location.toLowerCase())}`, {
    waitUntil: 'domcontentloaded'
  });
  await page.locator('.tenant-route-context').waitFor({timeout: 10000});
  if (await page.locator('.tenant-route-context strong').innerText() !== location) {
    throw new Error('registration did not normalize and bind the tenant from the dedicated URL');
  }
  if (await page.locator('.tenant-card input').count() !== 5) {
    throw new Error('registration must not expose an editable tenant/location input');
  }
  await page.screenshot({path: path.join(artifactDir, 'register-tenant-bound.png'), fullPage: true});

  await page.goto(`${baseUrl}/#/register`, {waitUntil: 'domcontentloaded'});
  await page.locator('.tenant-route-context-error').waitFor({timeout: 10000});
  if (!(await page.locator('.tenant-primary').isDisabled())) {
    throw new Error('registration must be disabled when the dedicated URL has no tenant');
  }
}

async function chartFillSnapshot(page) {
  return page.evaluate(() => {
    const chart = document.querySelector('.chartWrap');
    const panelBody = chart && chart.closest('.tradePanelBody');
    const header = chart && chart.querySelector('.head');
    const container = chart && chart.querySelector('.TVChartContainer');
    const iframe = container && container.querySelector('iframe');
    if (!chart || !panelBody || !header || !container || !iframe) return null;
    const height = element => element.getBoundingClientRect().height;
    return {
      panelBody: height(panelBody),
      chart: height(chart),
      header: height(header),
      container: height(container),
      iframe: height(iframe)
    };
  });
}

function assertChartFillsPanel(snapshot) {
  if (!snapshot ||
      Math.abs(snapshot.chart - snapshot.panelBody) > 2 ||
      Math.abs(snapshot.container - (snapshot.chart - snapshot.header)) > 2 ||
      Math.abs(snapshot.iframe - snapshot.container) > 2 ||
      snapshot.container < 300) {
    throw new Error(`TradingView chart does not fill its workspace panel: ${JSON.stringify(snapshot)}`);
  }
}

async function login(page) {
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {
    waitUntil: 'domcontentloaded'
  });
  const loginLanguages = page.locator('.loginLanguageSwitch button');
  if (await loginLanguages.count() !== 2) throw new Error('login language switch is missing');
  await loginLanguages.nth(1).click();
  await page.getByText('Username', {exact: true}).waitFor({timeout: 10000});
  await loginLanguages.nth(0).click();
  await page.getByText('用户名', {exact: true}).waitFor({timeout: 10000});
  await loginLanguages.nth(1).click();
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
  const loginSession = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loginData') || '{}'));
  if (Number(loginSession.code) !== 0 || loginSession.user_id !== username ||
      String(loginSession.location || '').toUpperCase() !== location) {
    throw new Error(`websocket login failed: ${JSON.stringify(loginSession)}`);
  }
  await page.locator('.tradeGrid').waitFor({timeout: 60000});
  await page.waitForTimeout(2500);
}

async function layoutSnapshot(page) {
  return page.evaluate(() => {
    const key = Object.keys(localStorage).find(item => item.startsWith('dc-trade-layout-v1:'));
    return {key, value: key ? localStorage.getItem(key) : null};
  });
}

function layoutItem(snapshot, breakpoint, key) {
  if (!snapshot.value) return null;
  const layouts = JSON.parse(snapshot.value);
  return (layouts[breakpoint] || []).find(item => item.i === key) || null;
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await verifyTenantRouteBinding(page);
    await login(page);
    const initialChartFill = await chartFillSnapshot(page);
    assertChartFillsPanel(initialChartFill);

    // Establish a deterministic English default before exercising persistence.
    await page.locator('.languageSwitch button').nth(1).click();
    const resetLayoutButton = page.getByRole('button', {name: 'Reset layout', exact: true});
    if (await resetLayoutButton.count() !== 1) throw new Error('reset layout control is missing');
    await resetLayoutButton.click();
    await page.waitForTimeout(500);

    const panels = page.locator('.tradePanel');
    if (await panels.count() !== 5) throw new Error('expected five trading workspace panels');
    if (await page.locator('.layoutToolbar').count() !== 0 ||
        await page.getByRole('button', {name: /Lock layout|Customize layout/}).count() !== 0) {
      throw new Error('manual layout edit/lock controls must not be visible');
    }
    if (await page.locator('.panelDragZone').count() !== 5 ||
        await page.locator('.panelDragHandle').count() !== 0) {
      throw new Error('workspace panels must use hover drag zones without persistent handles');
    }
    await page.waitForFunction(() => {
      const iframe = document.querySelector('.TVChartContainer iframe');
      if (!iframe || !iframe.contentDocument) return false;
      return iframe.contentWindow.getComputedStyle(iframe.contentDocument.documentElement)
        .getPropertyValue('--tv-color-toolbar-button-text-active').trim() === '#f7a600';
    }, null, {timeout: 30000});
    const chartTheme = await page.evaluate(() => {
      const iframe = document.querySelector('.TVChartContainer iframe');
      const style = iframe.contentWindow.getComputedStyle(iframe.contentDocument.documentElement);
      return {
        activeIcon: style.getPropertyValue('--tv-color-toolbar-button-text-active').trim(),
        icon: style.getPropertyValue('--tv-color-toolbar-button-text').trim(),
        pane: style.getPropertyValue('--tv-color-pane-background').trim()
      };
    });

    await page.locator('.symbolDiv').click();
    const marketDrawer = page.locator('.ant-drawer');
    const marketSearch = marketDrawer.getByPlaceholder('Search markets');
    await marketSearch.waitFor({timeout: 10000});
    await marketSearch.fill('NO_SUCH_MARKET');
    await marketDrawer.getByText('No markets found', {exact: true}).waitFor({timeout: 10000});
    await marketSearch.fill('BTC');
    await marketDrawer.getByText('BTCUSDT', {exact: true}).click();
    await marketDrawer.waitFor({state: 'hidden', timeout: 10000});

    await page.getByText('Last Price', {exact: true}).first().waitFor({timeout: 10000});
    const buyButton = page.getByRole('button', {name: 'Buy / Long'});
    await buyButton.click();
    await page.getByText('Enter an amount greater than 0.', {exact: true}).first().waitFor({timeout: 10000});

    await page.getByRole('button', {name: 'Limit', exact: true}).click();
    await page.getByLabel('Amount').fill('1');
    await buyButton.click();
    await page.getByText('Enter a limit price greater than 0.', {exact: true}).first().waitFor({timeout: 10000});

    await page.getByRole('button', {name: 'Conditional', exact: true}).click();
    await buyButton.click();
    await page.getByText('Enter a trigger price greater than 0.', {exact: true}).first().waitFor({timeout: 10000});
    await page.getByLabel('Execution Type').selectOption('Market');
    if (await page.getByLabel('Limit Price').isVisible()) {
      throw new Error('conditional market must not display a limit price');
    }
    if (!(await page.getByLabel('Time in Force').isDisabled())) {
      throw new Error('conditional market must force IOC');
    }
    await page.getByLabel('Reduce Only').check();
    if (!(await page.getByLabel('Reduce Only').isChecked())) {
      throw new Error('reduce-only control did not retain its state');
    }
    await page.getByRole('button', {name: 'Market', exact: true}).click();
    await page.getByLabel('Amount').fill('1e2');
    await buyButton.click();
    await page.getByText('Enter an amount greater than 0.', {exact: true}).first().waitFor({timeout: 10000});
    await page.waitForFunction(
      () => document.querySelectorAll('.ant-message-notice').length === 0,
      null,
      {timeout: 10000}
    );

    const before = await layoutSnapshot(page);
    const chartPanel = panels.nth(0);
    const beforeBox = await chartPanel.boundingBox();
    const handle = chartPanel.locator('.panelDragZone');
    const handleBox = await handle.boundingBox();
    if (!beforeBox || !handleBox) throw new Error('chart panel was not measurable');

    await handle.hover();
    await page.waitForTimeout(200);
    const hoverDragState = await handle.evaluate(element => ({
      cursor: getComputedStyle(element).cursor,
      indicatorOpacity: getComputedStyle(element, '::before').opacity
    }));
    if (hoverDragState.cursor !== 'move' || Number(hoverDragState.indicatorOpacity) < 0.9) {
      throw new Error(`hover drag affordance is not visible: ${JSON.stringify(hoverDragState)}`);
    }
    await page.mouse.down();
    // Move the wide chart below the occupied top-row panels. Dropping it into
    // the order-book/place-order cells is a collision and vertical compaction
    // legitimately restores the original layout.
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + 720, {steps: 30});
    await page.mouse.up();
    await page.waitForTimeout(800);

    const afterMove = await layoutSnapshot(page);
    const afterBox = await chartPanel.boundingBox();
    if (!afterMove.key || !afterMove.value || afterMove.value === before.value) {
      throw new Error(`dragged layout was not persisted to localStorage: ${JSON.stringify({
        beforeBox,
        afterBox,
        beforeLayout: before,
        afterLayout: afterMove,
        panelClass: await chartPanel.getAttribute('class')
      })}`);
    }
    if (!afterBox || (Math.abs(afterBox.x - beforeBox.x) < 20 && Math.abs(afterBox.y - beforeBox.y) < 20)) {
      throw new Error('drag gesture did not move the chart panel');
    }
    if ((await chartPanel.getAttribute('class') || '').includes('react-draggable-dragging')) {
      throw new Error('drag gesture did not release after crossing the chart iframe');
    }

    await chartPanel.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    const beforeResizeBox = await chartPanel.boundingBox();
    const resizeHandle = chartPanel.locator('.react-resizable-handle');
    const resizeHandleBox = await resizeHandle.boundingBox();
    if (!beforeResizeBox || !resizeHandleBox) throw new Error('chart resize handle was not measurable');
    await page.mouse.move(
      resizeHandleBox.x + resizeHandleBox.width / 2,
      resizeHandleBox.y + resizeHandleBox.height / 2
    );
    await page.mouse.down();
    await page.mouse.move(resizeHandleBox.x + 160, resizeHandleBox.y + 84, {steps: 20});
    await page.mouse.up();
    await page.waitForTimeout(800);
    const afterResizeBox = await chartPanel.boundingBox();
    if (!afterResizeBox ||
        (Math.abs(afterResizeBox.width - beforeResizeBox.width) < 40 &&
         Math.abs(afterResizeBox.height - beforeResizeBox.height) < 20)) {
      throw new Error('resize gesture did not resize the chart panel');
    }
    const customized = await layoutSnapshot(page);
    if (!customized.value || customized.value === afterMove.value) {
      throw new Error('resized layout was not persisted to localStorage');
    }
    await page.waitForTimeout(300);
    const resizedChartFill = await chartFillSnapshot(page);
    assertChartFillsPanel(resizedChartFill);

    const colors = await page.evaluate(() => ({
      page: getComputedStyle(document.querySelector('.tradeWrap')).backgroundColor,
      buy: getComputedStyle(document.querySelector('.orderBuyBtn')).backgroundColor,
      sell: getComputedStyle(document.querySelector('.orderSellBtn')).backgroundColor
    }));
    if (colors.page !== 'rgb(11, 14, 17)' ||
        colors.buy !== 'rgb(32, 178, 108)' ||
        colors.sell !== 'rgb(239, 69, 74)') {
      throw new Error(`professional trading theme is incomplete: ${JSON.stringify(colors)}`);
    }

    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForURL(`**/#/login?location=${encodeURIComponent(location)}`);
    await login(page);
    await page.locator('.tradeGrid').waitFor({timeout: 30000});
    await page.waitForTimeout(1500);
    const reloaded = await layoutSnapshot(page);
    const savedChart = layoutItem(customized, 'lg', 'chart');
    const reloadedChart = layoutItem(reloaded, 'lg', 'chart');
    if (!savedChart || !reloadedChart ||
        ['x', 'y', 'w', 'h'].some(field => savedChart[field] !== reloadedChart[field])) {
      throw new Error(`custom layout did not survive reload: ${JSON.stringify({savedChart, reloadedChart})}`);
    }

    await page.screenshot({path: path.join(artifactDir, 'workspace-en.png'), fullPage: true});

    await page.locator('.languageSwitch button').nth(0).click();
    await page.getByText('订单簿', {exact: true}).first().waitFor({timeout: 10000});
    await page.getByText('交易品种', {exact: true}).first().waitFor({timeout: 10000});
    if (await page.getByRole('button', {name: /编辑布局|锁定布局/}).count() !== 0) {
      throw new Error('Chinese manual layout controls must not be visible');
    }
    const chineseReset = page.getByRole('button', {name: '恢复默认', exact: true});
    if (await chineseReset.count() !== 1) throw new Error('Chinese reset layout control is missing');
    await page.screenshot({path: path.join(artifactDir, 'workspace-zh.png'), fullPage: true});
    await chineseReset.click();
    await page.waitForTimeout(600);
    const restoredChartBox = await panels.nth(0).boundingBox();
    if (!restoredChartBox || restoredChartBox.y > 200) {
      throw new Error(`reset layout did not restore the chart panel: ${JSON.stringify(restoredChartBox)}`);
    }

    if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);
    console.log(JSON.stringify({
      status: 'PASS',
      location,
      panels: 5,
      draggable: true,
      resizable: true,
      persisted: true,
      refreshRequiresWebSocketReauthentication: true,
      hoverDragZone: true,
      resetLayout: true,
      languages: ['en', 'zh'],
      bilingualLogin: true,
      orderInputValidation: true,
      conditionalOrderModes: true,
      reduceOnlyControl: true,
      tenantBoundRegistration: true,
      chartFillsPanel: {initial: initialChartFill, resized: resizedChartFill},
      bybitChartTheme: chartTheme,
      lastPriceHeader: true,
      searchableMarketSelector: true,
      professionalTheme: colors,
      artifacts: ['register-tenant-bound.png', 'workspace-en.png', 'workspace-zh.png']
    }, null, 2));
  } catch (error) {
    await page.screenshot({path: path.join(artifactDir, 'workspace-failure.png'), fullPage: true}).catch(() => {});
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
