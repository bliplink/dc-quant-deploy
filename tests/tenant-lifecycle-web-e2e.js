const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const locationA = process.env.E2E_LOCATION_A;
const locationB = process.env.E2E_LOCATION_B;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';
if (!locationA || !locationB) throw new Error('both tenant locations are required');
fs.mkdirSync(artifactDir, {recursive: true});

(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    await page.goto(`${baseUrl}/#/tenant`, {waitUntil: 'domcontentloaded'});
    await page.locator('.tenant-language button').nth(1).click();
    await page.getByRole('heading', {name: 'Tenant Services'}).waitFor({timeout: 15000});
    await page.getByRole('button', {name: 'Apply for tenant'}).waitFor();
    await page.getByRole('button', {name: 'Sign in to tenant'}).waitFor();
    await page.screenshot({path: path.join(artifactDir, 'tenant-landing-en.png'), fullPage: true});

    await page.goto(`${baseUrl}/#/apply`, {waitUntil: 'domcontentloaded'});
    await page.getByRole('heading', {name: 'Apply for a SaaS Trading Trial'}).waitFor({timeout: 15000});
    if (await page.locator('.tenant-card input').count() < 8) {
      throw new Error('trial application form is incomplete');
    }
    await page.screenshot({path: path.join(artifactDir, 'tenant-application-en.png'), fullPage: true});

    await page.setViewportSize({width: 390, height: 844});
    await page.goto(`${baseUrl}/#/register?location=${encodeURIComponent(locationA)}`,
                    {waitUntil: 'domcontentloaded'});
    await page.locator('.tenant-language button').nth(1).click();
    await page.getByRole('heading', {name: 'Create Trading Account'}).waitFor({timeout: 15000});
    const registerInputs = page.locator('.tenant-card input');
    if (await registerInputs.count() !== 5) {
      throw new Error('registration must not expose an editable tenant/location input');
    }
    const boundLocation = (await page.locator('.tenant-route-context strong').textContent() || '').trim();
    if (boundLocation !== locationA) {
      throw new Error(`dedicated URL did not bind registration location: ${boundLocation}`);
    }
    await page.screenshot({path: path.join(artifactDir, 'tenant-registration-mobile-en.png'), fullPage: true});

    // Control-plane pages now live in distinct Tenant/Platform Web services.
    // The separate tenant-platform-console-e2e.js checks login, permissions,
    // account management and mobile layouts against those actual services.
    await page.goto(`${baseUrl}/#/tenant?location=${encodeURIComponent(locationB)}`,
                    {waitUntil: 'domcontentloaded'});
    await page.locator('.tenant-language button').nth(1).click();
    await page.getByRole('button', {name: 'Sign in to tenant'}).click();
    await page.waitForURL(`**/tenant-console/?location=${locationB}`, {timeout: 15000});
    await page.getByText('Tenant Console', {exact: true}).waitFor({timeout: 15000});

    if (pageErrors.length) throw new Error(`page errors: ${pageErrors.join(' | ')}`);
    console.log(JSON.stringify({status: 'PASS', locationA, locationB,
                                screenshots: fs.readdirSync(artifactDir).sort()}));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
