const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const username = process.env.E2E_USER || 'webbuyer';
const password = process.env.E2E_PASSWORD;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';

if (!password) throw new Error('E2E_PASSWORD is required');
fs.mkdirSync(artifactDir, {recursive: true});

async function token(page) {
  return page.evaluate(() => sessionStorage.getItem('ff-dex-token') || '');
}

async function login(page) {
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {waitUntil: 'domcontentloaded'});
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();
  await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
  await page.locator('.tradeWrap').waitFor({timeout: 60000});
  await page.waitForFunction(() => Boolean(sessionStorage.getItem('ff-dex-token')));
}

async function waitForRotatedToken(page, oldToken) {
  await page.waitForFunction(previous => {
    const current = sessionStorage.getItem('ff-dex-token');
    return Boolean(current && current !== previous);
  }, oldToken, {timeout: 60000});
  return token(page);
}

async function loginWithToken(page, candidateToken, requestedLocation = location) {
  return page.evaluate(async ({candidateToken, requestedLocation, username}) => {
    const response = await fetch('/httpapi/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        serverName: 'LoginSvr',
        method: 'SYS.ATS.LOGIN',
        content: {
          method: 'login',
          user_id: username,
          password: candidateToken,
          client_type: 'WEB',
          Location: requestedLocation,
          authType: 'TOKEN',
          cid: `TOKEN_REPLAY_${Date.now()}`
        }
      })
    });
    return response.json();
  }, {candidateToken, requestedLocation, username});
}

async function userInfo(page, candidateToken) {
  return page.evaluate(async candidateToken => {
    const response = await fetch('/httpapi/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', sessionId: candidateToken},
      body: JSON.stringify({
        serverName: 'LoginSvr',
        method: 'SYS.ATS.LOGIN',
        content: {method: 'userInfo', token: candidateToken, cid: `SESSION_INFO_${Date.now()}`}
      })
    });
    return response.json();
  }, candidateToken);
}

function expectRejected(label, result) {
  if (Number(result.code) === 0) throw new Error(`${label} unexpectedly succeeded: ${JSON.stringify(result)}`);
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 900}});
  const page = await context.newPage();
  try {
    await login(page);
    const token1 = await token(page);

    const remembered = await page.evaluate(() => {
      const raw = localStorage.getItem('userRemember');
      return raw ? JSON.parse(atob(raw)) : {};
    });
    if (Object.prototype.hasOwnProperty.call(remembered, 'info2')) {
      throw new Error('legacy remembered password was not removed');
    }

    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
    const token2 = await waitForRotatedToken(page, token1);
    expectRejected('rotated token replay', await loginWithToken(page, token1));
    expectRejected('cross-location token login', await loginWithToken(page, token2, `${location}_OTHER`));
    const currentInfo = await userInfo(page, token2);
    if (Number(currentInfo.code) !== 0 || currentInfo.data.user_id !== username || currentInfo.data.location !== location) {
      throw new Error(`rotated token is not authoritative: ${JSON.stringify(currentInfo)}`);
    }

    await context.setOffline(true);
    await page.waitForTimeout(1200);
    await context.setOffline(false);
    const token3 = await waitForRotatedToken(page, token2);
    expectRejected('disconnected token replay', await loginWithToken(page, token2));
    await page.locator('.logoutButton').click();
    await page.waitForURL(`**/#/login?location=${encodeURIComponent(location)}`, {timeout: 30000});
    await page.waitForFunction(() => !sessionStorage.getItem('ff-dex-token'));
    expectRejected('logged-out token reuse', await userInfo(page, token3));

    await page.screenshot({path: path.join(artifactDir, 'websocket-session-logout.png'), fullPage: true});
    console.log(JSON.stringify({
      status: 'PASS',
      location,
      user: username,
      refreshResume: true,
      disconnectResume: true,
      oneTimeRotation: true,
      crossLocationRejected: true,
      logoutRevoked: true,
      passwordPersisted: false,
      artifact: 'websocket-session-logout.png'
    }, null, 2));
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
