'use strict';

const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.ROBOT_SOAK_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.ROBOT_SOAK_LOCATION || 'WEB_E2E';
const user = process.env.ROBOT_SOAK_VIEWER || 'robotsoakmaker';
const secretFile = process.env.ROBOT_SOAK_SECRET_FILE || '/secrets/runtime.env';
const stateDir = process.env.ROBOT_SOAK_STATE_DIR || '/state';
const sampleMs = Number(process.env.ROBOT_SOAK_WEB_SAMPLE_MS || 250);

function secret(name) {
  const content = fs.readFileSync(secretFile, 'utf8');
  const prefix = `${name}=`;
  const line = content.split(/\r?\n/).find(item => item.startsWith(prefix));
  return line ? line.slice(prefix.length).trim() : '';
}

const password = secret('ROBOT_SOAK_PASSWORD');
if (!password) throw new Error('ROBOT_SOAK_PASSWORD is missing from the protected runtime file');
fs.mkdirSync(stateDir, {recursive: true});

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const emit = record => process.stdout.write(`${JSON.stringify({time: new Date().toISOString(), ...record})}\n`);

async function openTrade(browser) {
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().startsWith('time order violation')) {
      pageErrors.push(message.text());
    }
  });
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {waitUntil: 'domcontentloaded'});
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(user);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();
  await page.waitForFunction(() => Boolean(sessionStorage.getItem('loginData')), null, {timeout: 30000});
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 30000});
  await page.locator('.tradeWrap').waitFor({timeout: 60000});
  return {context, page, pageErrors};
}

async function monitorSession(browser) {
  const {context, page, pageErrors} = await openTrade(browser);
  let samples = 0;
  let gapSamples = 0;
  let minBids = Number.MAX_SAFE_INTEGER;
  let minAsks = Number.MAX_SAFE_INTEGER;
  let screenshotWritten = false;
  let everReady = false;
  emit({event: 'web_monitor_connected', location, user});
  try {
    while (true) {
      const sample = await page.evaluate(() => {
        const askRows = document.querySelectorAll('.orderBookWrap .showDiv .ask-container > .bid').length;
        const bidRows = document.querySelectorAll('.orderBookWrap .showDiv .ask-container + div + div > .bid').length;
        const lastPrice = document.querySelector('.orderBookWrap .showDiv .last-price')?.textContent?.trim() || '';
        const markPrice = document.querySelector('.orderBookWrap .showDiv .mark-price')?.textContent?.trim() || '';
        const loginData = JSON.parse(sessionStorage.getItem('loginData') || '{}');
        return {askRows, bidRows, lastPrice, markPrice, userId: loginData.user_id, tenant: loginData.location};
      });
      if (sample.userId !== user || sample.tenant !== location) {
        throw new Error(`authoritative web session changed: ${JSON.stringify(sample)}`);
      }
      samples += 1;
      const ready = sample.bidRows >= 10 && sample.askRows >= 10 && sample.lastPrice && sample.lastPrice !== '--';
      if (ready) {
        everReady = true;
        minBids = Math.min(minBids, sample.bidRows);
        minAsks = Math.min(minAsks, sample.askRows);
      }
      if (everReady && !ready) {
        gapSamples += 1;
        emit({event: 'web_depth_gap', sample, samples, gapSamples});
        if (!screenshotWritten && samples > 20) {
          await page.screenshot({path: path.join(stateDir, 'web-depth-gap.png'), fullPage: true});
          screenshotWritten = true;
        }
      } else if (!everReady && samples % Math.max(1, Math.round(5000 / sampleMs)) === 0) {
        emit({event: 'web_monitor_warming', sample, samples});
      }
      if (samples % Math.max(1, Math.round(60000 / sampleMs)) === 0) {
        emit({event: 'web_minute', samples, gapSamples, minBids, minAsks, pageErrors: pageErrors.splice(0)});
      }
      await sleep(sampleMs);
    }
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    while (true) {
      try {
        await monitorSession(browser);
      } catch (error) {
        emit({event: 'web_monitor_error', error: error.stack || String(error)});
        await sleep(3000);
      }
    }
  } finally {
    await browser.close();
  }
})().catch(error => {
  emit({event: 'web_monitor_fatal', error: error.stack || String(error)});
  process.exit(1);
});
