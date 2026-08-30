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

function requestMethod(response) {
  try {
    const body = response.request().postDataJSON();
    return body && (body.method || (body.content && body.content.method));
  } catch (error) {
    return '';
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
  const responsePromise = page.waitForResponse(
    response => response.url().includes('/httpapi/') && requestMethod(response) === 'SYS.ATS.LOGIN',
    {timeout: 60000}
  );
  await page.locator('.loginWrap .ant-btn-primary').click();
  const response = await responsePromise;
  const body = await response.json();
  if (Number(body.code) !== 0 || body.data.user_id !== username || body.data.location !== location) {
    throw new Error(`login failed: ${JSON.stringify(body)}`);
  }
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
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
    await login(page);

    // Establish a deterministic English default before exercising persistence.
    await page.locator('.languageSwitch button').nth(1).click();
    await page.getByRole('button', {name: 'Reset layout'}).click();
    await page.waitForTimeout(500);

    const panels = page.locator('.tradePanel');
    if (await panels.count() !== 5) throw new Error('expected five trading workspace panels');
    if (await page.locator('.panelDragHandle').count() !== 5) {
      throw new Error('all workspace panels must expose a drag handle while unlocked');
    }

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
    await page.getByText('Enter an amount greater than 0.', {exact: true}).waitFor({timeout: 10000});

    await page.getByRole('button', {name: 'Limit', exact: true}).click();
    await page.getByLabel('Amount').fill('1');
    await buyButton.click();
    await page.getByText('Enter a limit price greater than 0.', {exact: true}).waitFor({timeout: 10000});

    await page.getByRole('button', {name: 'Conditional', exact: true}).click();
    await buyButton.click();
    await page.getByText('Enter a trigger price greater than 0.', {exact: true}).waitFor({timeout: 10000});
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
    await page.getByText('Enter an amount greater than 0.', {exact: true}).waitFor({timeout: 10000});

    const before = await layoutSnapshot(page);
    const chartPanel = panels.nth(0);
    const beforeBox = await chartPanel.boundingBox();
    const handle = chartPanel.locator('.panelDragHandle');
    const handleBox = await handle.boundingBox();
    if (!beforeBox || !handleBox) throw new Error('chart panel was not measurable');

    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(handleBox.x + 360, handleBox.y + 250, {steps: 20});
    await page.mouse.up();
    await page.waitForTimeout(800);

    const afterBox = await chartPanel.boundingBox();
    const afterMove = await layoutSnapshot(page);
    if (!afterMove.key || !afterMove.value || afterMove.value === before.value) {
      throw new Error('dragged layout was not persisted to localStorage');
    }
    if (!afterBox || (Math.abs(afterBox.x - beforeBox.x) < 20 && Math.abs(afterBox.y - beforeBox.y) < 20)) {
      throw new Error('drag gesture did not move the chart panel');
    }

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
    await page.locator('.tradeGrid').waitFor({timeout: 30000});
    await page.waitForTimeout(1500);
    const reloaded = await layoutSnapshot(page);
    const savedChart = layoutItem(customized, 'lg', 'chart');
    const reloadedChart = layoutItem(reloaded, 'lg', 'chart');
    if (!savedChart || !reloadedChart ||
        ['x', 'y', 'w', 'h'].some(field => savedChart[field] !== reloadedChart[field])) {
      throw new Error(`custom layout did not survive reload: ${JSON.stringify({savedChart, reloadedChart})}`);
    }

    await page.getByRole('button', {name: 'Lock layout'}).click();
    if (await page.locator('.panelDragHandle').count() !== 0) {
      throw new Error('drag handles remain active after locking the layout');
    }
    await page.screenshot({path: path.join(artifactDir, 'workspace-en.png'), fullPage: true});

    await page.locator('.languageSwitch button').nth(0).click();
    await page.getByRole('button', {name: '编辑布局'}).waitFor({timeout: 10000});
    await page.getByText('订单簿', {exact: true}).first().waitFor({timeout: 10000});
    await page.getByText('交易品种', {exact: true}).first().waitFor({timeout: 10000});
    await page.screenshot({path: path.join(artifactDir, 'workspace-zh.png'), fullPage: true});

    if (pageErrors.length) throw new Error(`page errors: ${JSON.stringify(pageErrors)}`);
    console.log(JSON.stringify({
      status: 'PASS',
      location,
      panels: 5,
      draggable: true,
      resizable: true,
      persisted: true,
      lockable: true,
      languages: ['en', 'zh'],
      bilingualLogin: true,
      orderInputValidation: true,
      conditionalOrderModes: true,
      reduceOnlyControl: true,
      lastPriceHeader: true,
      searchableMarketSelector: true,
      professionalTheme: colors,
      artifacts: ['workspace-en.png', 'workspace-zh.png']
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
