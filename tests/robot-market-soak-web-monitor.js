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
const browserCycleMs = Number(process.env.ROBOT_SOAK_WEB_BROWSER_CYCLE_MS || 600000);
const operationTimeoutMs = Number(process.env.ROBOT_SOAK_WEB_OPERATION_TIMEOUT_MS || 15000);
const heartbeatFile = path.join(stateDir, 'web-heartbeat.json');
const webMetricsFile = path.join(stateDir, 'web-metrics.csv');

for (const [name, value] of Object.entries({sampleMs, browserCycleMs, operationTimeoutMs})) {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} must be a positive number`);
}

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

function withTimeout(promise, timeoutMs, operation) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${operation} timed out after ${timeoutMs}ms`)), timeoutMs);
    promise.then(
      value => { clearTimeout(timer); resolve(value); },
      error => { clearTimeout(timer); reject(error); }
    );
  });
}

function writeHeartbeat(record) {
  const temporary = `${heartbeatFile}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({time: new Date().toISOString(), pid: process.pid, ...record})}\n`);
  fs.renameSync(temporary, heartbeatFile);
}

function appendWebMetric(record) {
  if (!fs.existsSync(webMetricsFile) || fs.statSync(webMetricsFile).size === 0) {
    fs.writeFileSync(webMetricsFile,
      'time,samples,gap_samples,min_bids,max_bids,min_asks,max_asks,page_errors\n');
  }
  fs.appendFileSync(webMetricsFile,
    `${new Date().toISOString()},${record.samples},${record.gapSamples},${record.minBids},` +
    `${record.maxBids},${record.minAsks},${record.maxAsks},${record.pageErrorCount}\n`);
}

async function openTrade(browser) {
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  try {
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
  } catch (error) {
    await withTimeout(context.close(), operationTimeoutMs, 'failed-login context.close').catch(() => {});
    throw error;
  }
}

async function monitorSession(browser) {
  const {context, page, pageErrors} = await openTrade(browser);
  const cycleStartedAt = Date.now();
  let samples = 0;
  let gapSamples = 0;
  let minBids = Number.MAX_SAFE_INTEGER;
  let minAsks = Number.MAX_SAFE_INTEGER;
  let maxBids = 0;
  let maxAsks = 0;
  let screenshotWritten = false;
  let lastHealthyScreenshotSample = 0;
  let everReady = false;
  emit({event: 'web_monitor_connected', location, user});
  try {
    while (Date.now() - cycleStartedAt < browserCycleMs) {
      const sample = await withTimeout(page.evaluate(() => {
        const wrappers = [...document.querySelectorAll('.orderBookWrap')];
        const visibleWrappers = wrappers.filter(element => {
          const style = window.getComputedStyle(element);
          const box = element.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
        });
        const orderBook = visibleWrappers[0];
        const visibleRows = selector => [...(orderBook?.querySelectorAll(selector) || [])].filter(element => {
          const row = element.getBoundingClientRect();
          const container = element.parentElement?.getBoundingClientRect();
          if (!container || row.width <= 0 || row.height <= 0 || container.height <= 0) return false;
          return Math.min(row.bottom, container.bottom) - Math.max(row.top, container.top) >= 10;
        }).length;
        const askRows = visibleRows('.showDiv .ask-container > .bid');
        const bidRows = visibleRows('.showDiv .ask-container + div + div > .bid');
        const lastPrice = orderBook?.querySelector('.showDiv .last-price')?.textContent?.trim() || '';
        const markPrice = orderBook?.querySelector('.showDiv .mark-price')?.textContent?.trim() || '';
        const loginData = JSON.parse(sessionStorage.getItem('loginData') || '{}');
        return {askRows, bidRows, lastPrice, markPrice, wrapperCount: wrappers.length,
          visibleWrapperCount: visibleWrappers.length, userId: loginData.user_id, tenant: loginData.location};
      }), operationTimeoutMs, 'page.evaluate');
      if (sample.userId !== user || sample.tenant !== location) {
        throw new Error(`authoritative web session changed: ${JSON.stringify(sample)}`);
      }
      samples += 1;
      const ready = sample.bidRows === 10 && sample.askRows === 10 && sample.lastPrice && sample.lastPrice !== '--';
      if (ready) {
        everReady = true;
        if (lastHealthyScreenshotSample === 0 || samples - lastHealthyScreenshotSample >= Math.round(600000 / sampleMs)) {
          await page.screenshot({path: path.join(stateDir, 'web-market-live.png'), fullPage: true});
          lastHealthyScreenshotSample = samples;
          emit({event: 'web_healthy_screenshot', sample, samples, path: 'web-market-live.png'});
        }
      }
      if (everReady) {
        minBids = Math.min(minBids, sample.bidRows);
        minAsks = Math.min(minAsks, sample.askRows);
        maxBids = Math.max(maxBids, sample.bidRows);
        maxAsks = Math.max(maxAsks, sample.askRows);
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
        const minuteErrors = pageErrors.splice(0);
        const metric = {samples, gapSamples, minBids, minAsks, maxBids, maxAsks,
          pageErrorCount: minuteErrors.length};
        appendWebMetric(metric);
        writeHeartbeat({...metric, status: 'healthy'});
        emit({event: 'web_minute', ...metric, pageErrors: minuteErrors});
      } else if (samples % Math.max(1, Math.round(1000 / sampleMs)) === 0) {
        writeHeartbeat({samples, gapSamples, minBids, minAsks, maxBids, maxAsks,
          pageErrorCount: pageErrors.length, status: 'sampling'});
      }
      await sleep(sampleMs);
    }
    emit({event: 'web_browser_cycle_complete', samples, gapSamples, browserCycleMs});
  } finally {
    await withTimeout(context.close(), operationTimeoutMs, 'context.close').catch(error => {
      emit({event: 'web_context_close_error', error: error.stack || String(error)});
    });
  }
}

(async () => {
  while (true) {
    let browser;
    try {
      browser = await withTimeout(chromium.launch({headless: true}), operationTimeoutMs, 'chromium.launch');
      await monitorSession(browser);
    } catch (error) {
      writeHeartbeat({status: 'error', error: String(error.message || error)});
      emit({event: 'web_monitor_error', error: error.stack || String(error)});
    } finally {
      if (browser) {
        await withTimeout(browser.close(), operationTimeoutMs, 'browser.close').catch(error => {
          emit({event: 'web_browser_close_error', error: error.stack || String(error)});
          process.exit(2);
        });
      }
    }
    await sleep(3000);
  }
})().catch(error => {
  emit({event: 'web_monitor_fatal', error: error.stack || String(error)});
  process.exit(1);
});
