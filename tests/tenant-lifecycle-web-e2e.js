const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const locationA = process.env.E2E_LOCATION_A;
const locationB = process.env.E2E_LOCATION_B;
const adminUser = process.env.E2E_ADMIN_USER || 'tenantadmin';
const adminPassword = process.env.E2E_ADMIN_PASSWORD_A;
const platformUser = process.env.PLATFORM_ADMIN_USERNAME;
const platformPassword = process.env.PLATFORM_ADMIN_PASSWORD;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';

for (const [name, value] of Object.entries({locationA, locationB, adminPassword, platformUser, platformPassword})) {
  if (!value) throw new Error(`${name} is required`);
}
fs.mkdirSync(artifactDir, {recursive: true});

function screenshotPath(name) {
  return path.join(artifactDir, name);
}

function requestMethod(response) {
  try {
    const body = response.request().postDataJSON();
    return body && (body.method || (body.content && body.content.method));
  } catch (_) {
    return '';
  }
}

async function login(page, username, password, location) {
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {waitUntil: 'domcontentloaded'});
  const languageButtons = page.locator('.loginLanguageSwitch button');
  await languageButtons.nth(1).click();
  await page.getByText('Username', {exact: true}).waitFor({timeout: 15000});
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  const responsePromise = page.waitForResponse(
    response => response.url().includes('/httpapi/') && requestMethod(response) === 'SYS.ATS.LOGIN',
    {timeout: 60000}
  );
  await page.locator('.loginWrap .ant-btn-primary').click();
  const body = await (await responsePromise).json();
  if (Number(body.code) !== 0 || body.data.location !== location) {
    throw new Error(`tenant login failed: ${JSON.stringify(body)}`);
  }
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/#/apply`, {waitUntil: 'domcontentloaded'});
    await page.locator('.tenant-language button').nth(1).click();
    await page.getByRole('heading', {name: 'Apply for a SaaS Trading Trial'}).waitFor({timeout: 15000});
    if (await page.locator('.tenant-card input').count() < 8) throw new Error('trial application form is incomplete');
    await page.screenshot({path: screenshotPath('tenant-application-en.png'), fullPage: true});

    await page.setViewportSize({width: 390, height: 844});
    await page.goto(`${baseUrl}/#/register?location=${encodeURIComponent(locationA)}`, {waitUntil: 'domcontentloaded'});
    await page.locator('.tenant-language button').nth(1).click();
    await page.getByRole('heading', {name: 'Create Trading Account'}).waitFor({timeout: 15000});
    const registerInputs = page.locator('.tenant-card input');
    if (await registerInputs.nth(0).inputValue() !== locationA) throw new Error('dedicated URL did not bind registration location');
    await page.screenshot({path: screenshotPath('tenant-registration-mobile-en.png'), fullPage: true});

    await page.setViewportSize({width: 1600, height: 1000});
    await page.goto(`${baseUrl}/#/platform-login`, {waitUntil: 'domcontentloaded'});
    const platformInputs = page.locator('.tenant-card input');
    await platformInputs.nth(0).fill(platformUser);
    await platformInputs.nth(1).fill(platformPassword);
    const platformResponse = page.waitForResponse(
      response => response.url().includes('/httpapi/') && requestMethod(response) === 'SYS.ATS.LOGIN',
      {timeout: 60000}
    );
    await page.locator('.tenant-card .ant-btn-primary').click();
    const platformBody = await (await platformResponse).json();
    if (Number(platformBody.code) !== 0 || platformBody.data.location !== 'PLATFORM') {
      throw new Error(`platform login failed: ${JSON.stringify(platformBody)}`);
    }
    await page.waitForURL('**/#/platform-admin', {timeout: 60000});
    await page.getByText('Provisioned tenants', {exact: true}).click();
    await page.getByText(locationA, {exact: true}).waitFor({timeout: 30000});
    await page.getByText(locationB, {exact: true}).waitFor({timeout: 30000});
    await page.screenshot({path: screenshotPath('platform-tenant-operations-en.png'), fullPage: true});

    await page.evaluate(() => sessionStorage.clear());
    await login(page, adminUser, adminPassword, locationA);
    await page.goto(`${baseUrl}/#/tenant-admin?location=${encodeURIComponent(locationA)}`, {waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: 'Tenant Administration'}).waitFor({timeout: 30000});
    await page.getByText(locationA, {exact: true}).waitFor({timeout: 30000});
    await page.getByText('sharedtrader', {exact: true}).waitFor({timeout: 30000});
    await page.screenshot({path: screenshotPath('tenant-administration-en.png'), fullPage: true});

    await page.setViewportSize({width: 390, height: 844});
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: 'Tenant Administration'}).waitFor({timeout: 30000});
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    if (bodyWidth > 1800) throw new Error(`tenant admin mobile layout overflow is excessive: ${bodyWidth}px`);
    await page.screenshot({path: screenshotPath('tenant-administration-mobile-en.png'), fullPage: true});

    if (pageErrors.length) throw new Error(`page errors: ${pageErrors.join(' | ')}`);
    console.log(JSON.stringify({status: 'PASS', locationA, locationB, screenshots: fs.readdirSync(artifactDir).sort()}));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
