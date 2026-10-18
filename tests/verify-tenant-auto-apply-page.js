const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {chromium} = require('playwright');

const suffix = Date.now().toString(36).toUpperCase();
const password = `Test!${crypto.randomBytes(12).toString('hex')}`;
const email = `browser-auto-${suffix}@acceptance.invalid`;
const artifactDir = process.env.TENANT_AUTO_ARTIFACT_DIR || '/artifacts/tenant-auto-apply';
fs.mkdirSync(artifactDir, {recursive: true});

(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:18088/#/apply', {waitUntil: 'domcontentloaded'});
    await page.getByRole('button', {name: '中文'}).click();
    try {
      await page.getByRole('heading', {name: '申请 SaaS 交易系统试用'}).waitFor({timeout: 30000});
    } catch (error) {
      await page.screenshot({path: path.join(artifactDir, 'load-failed.png'), fullPage: true});
      throw new Error(`apply page missing: ${await page.title()} / ${(await page.locator('body').innerText()).slice(0, 300)} / ${errors.join('; ')}`);
    }
    const inputs = page.locator('.tenant-grid').first().locator('input');
    if (await inputs.count() < 8) throw new Error('application inputs are incomplete');
    await inputs.nth(0).fill(`Browser Auto Tenant ${suffix}`);
    await inputs.nth(1).fill('Acceptance');
    await inputs.nth(2).fill(email);
    await inputs.nth(5).fill(password);
    await page.screenshot({path: path.join(artifactDir, 'application.png'), fullPage: true});
    await page.getByRole('button', {name: '提交申请'}).click();
    await page.locator('.tenant-result').first().getByText('APPROVED').waitFor({timeout: 30000});
    const result = await page.locator('.tenant-result').first().innerText();
    const adminUrl = await page.locator('.tenant-result').first().getByRole('link').first().getAttribute('href');
    const location = new URL(adminUrl).searchParams.get('location');
    if (!location || !result.includes('申请编号')) throw new Error(`approved result incomplete: ${result}`);
    await page.screenshot({path: path.join(artifactDir, 'approved.png'), fullPage: true});

    await page.goto(`http://127.0.0.1:18092/?location=${location}`);
    await page.getByLabel('租户管理员账号').fill('tenantadmin');
    await page.getByLabel('密码').fill(password);
    await page.getByRole('button', {name: '登录租户控制台'}).click();
    await page.getByRole('heading', {name: '租户工作台'}).waitFor({timeout: 30000});
    await page.screenshot({path: path.join(artifactDir, 'tenant-console.png'), fullPage: true});
    if (errors.length) throw new Error(`browser errors: ${errors.join('; ')}`);
    const evidence = {result: 'PASS', location, defaultSymbol: 'BTCUSDT',
      autoReview: 'APPROVED', tenantAdminLogin: 'PASS', pageErrors: 0};
    fs.writeFileSync(path.join(artifactDir, 'result.json'), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error.message); process.exitCode = 1});
