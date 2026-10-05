const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const tenantPortalBaseUrl = process.env.TENANT_PORTAL_BASE_URL || 'http://127.0.0.1:18092';
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

async function tenantAdminLogin(page, username, password, location) {
  await page.goto(`${baseUrl}/#/tenant-login`, {waitUntil: 'domcontentloaded'});
  await page.getByRole('heading', {name: 'Tenant Administration Login'}).waitFor({timeout: 15000});
  const inputs = page.locator('.tenant-card input');
  if (await inputs.count() !== 3) throw new Error('tenant login must contain location, username and password');
  if (await inputs.nth(0).inputValue()) throw new Error('tenant login location must not depend on a URL query');
  await inputs.nth(0).fill(location);
  await inputs.nth(1).fill(username);
  await inputs.nth(2).fill(password);
  await page.locator('.tenant-card .ant-btn-primary').click();
  await page.waitForURL('**/#/tenant-admin', {timeout: 60000});
  await page.getByRole('heading', {name: 'Tenant Administration'}).waitFor({timeout: 60000});
  const loginData = await page.evaluate(() => JSON.parse(sessionStorage.getItem('dc-tenant-admin-session') || '{}'));
  if (loginData.location !== location || loginData.client_type !== 'TenantAdmin') {
    throw new Error(`tenant administration session mismatch: ${JSON.stringify(loginData)}`);
  }
  const leakedTradeSession = await page.evaluate(() => ({token: sessionStorage.getItem('ff-dex-token'), data: sessionStorage.getItem('loginData')}));
  if (leakedTradeSession.token || leakedTradeSession.data) {
    throw new Error(`tenant administration login leaked into trading session: ${JSON.stringify(leakedTradeSession)}`);
  }
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await page.goto(`${tenantPortalBaseUrl}/`, {waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: 'Tenant Portal'}).waitFor({timeout: 15000});
    await page.getByRole('button', {name: 'Create Tenant', exact: true}).waitFor();
    await page.getByRole('button', {name: 'Tenant Sign In', exact: true}).waitFor();
    const portalText = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
    for (const internalCopy of ['Location', 'Application ID', 'sandbox', 'Provisioning']) {
      if (portalText.includes(internalCopy)) throw new Error(`tenant portal exposes internal copy: ${internalCopy}`);
    }

    await page.goto(`${tenantPortalBaseUrl}/?mode=apply`, {waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: 'Create Tenant'}).waitFor({timeout: 15000});
    const tenantInputs = page.locator('.tenant-application-form input');
    if (await tenantInputs.count() !== 4) throw new Error('tenant creation form must contain organization, email, admin username and admin password');
    const readOnlyAdmin = tenantInputs.nth(2);
    if (!(await readOnlyAdmin.isDisabled().catch(() => false)) && !(await readOnlyAdmin.getAttribute('readonly') !== null)) {
      throw new Error('tenant admin username must be read-only');
    }
    if (await readOnlyAdmin.inputValue() !== 'tenantadmin') throw new Error('tenant admin username is unexpected');
    await page.screenshot({path: screenshotPath('tenant-application-en.png'), fullPage: true});

    await page.setViewportSize({width: 390, height: 844});
    await page.goto(`${baseUrl}/#/register?location=${encodeURIComponent(locationA)}`, {waitUntil: 'domcontentloaded'});
    await page.locator('.tenant-language button').nth(1).click();
    await page.getByRole('heading', {name: 'Create account'}).waitFor({timeout: 15000});
    const registerInputs = page.locator('.tenant-card input');
    if (await registerInputs.count() !== 5) {
      throw new Error('registration must not expose an editable tenant/location input');
    }
    const boundLocation = (await page.locator('.tenant-route-context strong').textContent() || '').trim();
    if (boundLocation !== locationA) {
      throw new Error(`tenant ID did not bind registration to the requested tenant: ${boundLocation}`);
    }
    await page.screenshot({path: screenshotPath('tenant-registration-mobile-en.png'), fullPage: true});

    await page.setViewportSize({width: 1600, height: 1000});
    await page.goto(`${baseUrl}/#/platform-login`, {waitUntil: 'domcontentloaded'});
    const platformInputs = page.locator('.tenant-card input');
    await platformInputs.nth(0).fill(platformUser);
    await platformInputs.nth(1).fill(platformPassword);
    await page.locator('.tenant-card .ant-btn-primary').click();
    await page.waitForURL('**/#/platform-admin', {timeout: 60000});
    await page.getByRole('heading', {name: 'SaaS Platform Operations'}).waitFor({timeout: 60000});
    const platformData = await page.evaluate(() => JSON.parse(sessionStorage.getItem('dc-platform-admin-session') || '{}'));
    if (platformData.location !== 'PLATFORM') throw new Error(`platform session mismatch: ${JSON.stringify(platformData)}`);
    const platformTradeSession = await page.evaluate(() => ({token: sessionStorage.getItem('ff-dex-token'), data: sessionStorage.getItem('loginData')}));
    if (platformTradeSession.token || platformTradeSession.data) {
      throw new Error(`platform login leaked into trading session: ${JSON.stringify(platformTradeSession)}`);
    }
    await page.getByText('Provisioned tenants', {exact: true}).click();
    await page.getByText(locationA, {exact: true}).waitFor({timeout: 30000});
    await page.getByText(locationB, {exact: true}).waitFor({timeout: 30000});
    await page.screenshot({path: screenshotPath('platform-tenant-operations-en.png'), fullPage: true});
    await page.getByRole('button', {name: 'Sign out'}).click();
    await page.waitForURL('**/#/platform-login', {timeout: 30000});
    await page.waitForFunction(() => !sessionStorage.getItem('dc-platform-admin-token'), null, {timeout: 30000});

    await page.evaluate(() => sessionStorage.clear());
    await tenantAdminLogin(page, adminUser, adminPassword, locationA);
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
    await page.getByRole('button', {name: 'Sign out'}).click();
    await page.waitForURL('**/#/tenant-login', {timeout: 30000});
    await page.waitForFunction(() => !sessionStorage.getItem('dc-tenant-admin-token'), null, {timeout: 30000});

    if (pageErrors.length) throw new Error(`page errors: ${pageErrors.join(' | ')}`);
    console.log(JSON.stringify({status: 'PASS', locationA, locationB, screenshots: fs.readdirSync(artifactDir).sort()}));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
