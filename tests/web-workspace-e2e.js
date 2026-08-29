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
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  const responsePromise = page.waitForResponse(
    response => response.url().includes('/httpapi/') && requestMethod(response) === 'SYS.ATS.LOGIN',
    {timeout: 30000}
  );
  await page.locator('.loginWrap button').click();
  const response = await responsePromise;
  const body = await response.json();
  if (Number(body.code) !== 0 || body.data.user_id !== username || body.data.location !== location) {
    throw new Error(`login failed: ${JSON.stringify(body)}`);
  }
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`);
  await page.locator('.tradeGrid').waitFor({timeout: 30000});
  await page.waitForTimeout(2500);
}

async function layoutSnapshot(page) {
  return page.evaluate(() => {
    const key = Object.keys(localStorage).find(item => item.startsWith('dc-trade-layout-v1:'));
    return {key, value: key ? localStorage.getItem(key) : null};
  });
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
    const after = await layoutSnapshot(page);
    if (!after.key || !after.value || after.value === before.value) {
      throw new Error('dragged layout was not persisted to localStorage');
    }
    if (!afterBox || (Math.abs(afterBox.x - beforeBox.x) < 20 && Math.abs(afterBox.y - beforeBox.y) < 20)) {
      throw new Error('drag gesture did not move the chart panel');
    }

    await page.reload({waitUntil: 'domcontentloaded'});
    await page.locator('.tradeGrid').waitFor({timeout: 30000});
    await page.waitForTimeout(1500);
    const reloaded = await layoutSnapshot(page);
    if (reloaded.value !== after.value) throw new Error('custom layout did not survive reload');

    await page.getByRole('button', {name: 'Lock layout'}).click();
    if (await page.locator('.panelDragHandle').count() !== 0) {
      throw new Error('drag handles remain active after locking the layout');
    }
    await page.screenshot({path: path.join(artifactDir, 'workspace-en.png'), fullPage: true});

    await page.locator('.languageSwitch button').nth(0).click();
    await page.getByRole('button', {name: '编辑布局'}).waitFor({timeout: 10000});
    await page.getByText('订单簿', {exact: true}).first().waitFor({timeout: 10000});
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
