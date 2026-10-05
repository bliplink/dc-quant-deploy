const crypto = require('crypto');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = String(process.env.E2E_LOCATION || '').trim().toUpperCase();

if (!location) throw new Error('E2E_LOCATION is required');

const randomHex = bytes => crypto.randomBytes(bytes).toString('hex');

(async () => {
  const username = 'resume' + randomHex(3);
  const password = 'Tr9!' + randomHex(8);
  const email = username + '@example.com';

  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    const started = Date.now();
    await page.goto(`${baseUrl}/#/register?location=${encodeURIComponent(location)}`, {
      waitUntil: 'domcontentloaded',
      timeout: 30000
    });

    const english = page.locator('.tenant-language button').filter({hasText: 'EN'});
    if (await english.count()) await english.click();

    await page.getByRole('heading', {name: 'Create account'}).waitFor({timeout: 15000});
    const inputs = page.locator('.tenant-card input');
    if (await inputs.count() !== 5) throw new Error('registration form input count mismatch');

    const boundLocation = (await page.locator('.tenant-route-context strong').textContent() || '').trim().toUpperCase();
    if (boundLocation !== location) throw new Error(`registration tenant binding mismatch: ${boundLocation}`);

    await inputs.nth(0).fill(username);
    await inputs.nth(1).fill('Resume Acceptance');
    await inputs.nth(2).fill(email);
    await inputs.nth(3).fill(password);
    await inputs.nth(4).fill(password);
    await page.getByRole('button', {name: 'Create account', exact: true}).click();

    await page.waitForURL(url => url.hash === `#/trade?location=${location}`, {timeout: 60000});
    await page.waitForSelector('.tradeWrap', {state: 'attached', timeout: 60000});
    await page.waitForTimeout(1000);

    if (await page.locator('.placeOrderWrap.publicMode').count() !== 0) {
      throw new Error('registration entered anonymous trade mode');
    }
    if (page.url().includes('/login')) throw new Error('registration redirected to login');

    const registerToTradeMs = Date.now() - started;
    const reloadStarted = Date.now();

    await page.reload({waitUntil: 'domcontentloaded', timeout: 30000});
    await page.waitForSelector('.tradeWrap', {state: 'attached', timeout: 60000});
    await page.waitForTimeout(2500);

    if (page.url().includes('/login')) throw new Error(`reload redirected to login: ${page.url()}`);
    if (await page.locator('.placeOrderWrap.publicMode').count() !== 0) {
      throw new Error('reload restored anonymous trade mode');
    }
    if (await page.locator('.publicActions').count() !== 0) {
      throw new Error('reload exposed anonymous header actions');
    }

    const reloadResumeMs = Date.now() - reloadStarted;

    await page.setViewportSize({width: 390, height: 844});
    await page.waitForTimeout(700);
    const tabs = await page.locator('.mobileLowerTabs button').allTextContents();
    const expected = ['Positions', 'Open Orders', 'Order History', 'Trade History', 'Funds'];
    if (JSON.stringify(tabs) !== JSON.stringify(expected)) {
      throw new Error(`mobile tabs mismatch: ${JSON.stringify(tabs)}`);
    }

    for (const label of ['Order History', 'Trade History', 'Funds']) {
      await page.locator('.mobileLowerTabs button').filter({hasText: label}).click();
      await page.waitForTimeout(250);
      if (page.url().includes('/login')) throw new Error(`${label} redirected to login`);
    }

    if (pageErrors.length) throw new Error(`page errors: ${pageErrors.join(' | ')}`);

    console.log(JSON.stringify({
      status: 'PASS',
      location,
      registrationAutoLogin: true,
      registerToTradeMs,
      reloadAuthenticated: true,
      reloadResumeMs,
      mobileTabs: tabs
    }));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
