const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright');

const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:18088';
const location = process.env.E2E_LOCATION || 'WEB_E2E';
const username = process.env.E2E_USER || 'webbuyer';
const password = process.env.E2E_PASSWORD;
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts';
const disconnectMarker = path.join(artifactDir, 'websocket-session-disconnect.ready');

if (!password) throw new Error('E2E_PASSWORD is required');
fs.mkdirSync(artifactDir, {recursive: true});

async function token(page) {
  return page.evaluate(() => sessionStorage.getItem('ff-dex-token') || '');
}

async function login(page, browserEvents) {
  await page.goto(`${baseUrl}/#/login?location=${encodeURIComponent(location)}`, {waitUntil: 'domcontentloaded'});
  const inputs = page.locator('.loginWrap input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill(password);
  await page.locator('.loginWrap .ant-btn-primary').click();
  try {
    await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
  } catch (error) {
    const diagnostics = await page.evaluate(() => ({
      url: window.location.href,
      title: document.title,
      body: document.body.innerText.slice(0, 1600),
      sessionToken: sessionStorage.getItem('ff-dex-token'),
      loginData: sessionStorage.getItem('loginData'),
      remembered: localStorage.getItem('userRemember'),
      buttonDisabled: Boolean(document.querySelector('.loginWrap .ant-btn-primary')?.disabled)
    }));
    await page.screenshot({path: path.join(artifactDir, 'websocket-session-login-failure.png'), fullPage: true});
    throw new Error(`login did not navigate: ${JSON.stringify(diagnostics)}; browser=${JSON.stringify(browserEvents)}; ${error.message}`);
  }
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
  const browserErrors = [];
  const browserEvents = [];
  page.on('pageerror', error => browserErrors.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    browserEvents.push(`console.${message.type()}: ${message.text()}`);
    if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`);
  });
  page.on('websocket', socket => {
    browserEvents.push(`websocket.opening: ${socket.url()}`);
    socket.on('close', () => browserEvents.push(`websocket.closed: ${socket.url()}`));
    socket.on('socketerror', error => browserEvents.push(`websocket.error: ${error}`));
  });
  try {
    await login(page, browserEvents);
    const token1 = await token(page);

    const remembered = await page.evaluate(() => {
      const raw = localStorage.getItem('userRemember');
      return raw ? JSON.parse(atob(raw)) : {};
    });
    if (Object.prototype.hasOwnProperty.call(remembered, 'info2')) {
      throw new Error('legacy remembered password was not removed');
    }
    if (browserErrors.length) throw new Error(`browser errors after login: ${JSON.stringify(browserErrors)}`);

    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForURL(`**/#/trade?location=${encodeURIComponent(location)}`, {timeout: 60000});
    const token2 = await waitForRotatedToken(page, token1);
    expectRejected('rotated token replay', await loginWithToken(page, token1));
    expectRejected('cross-location token login', await loginWithToken(page, token2, `${location}_OTHER`));
    const currentInfo = await userInfo(page, token2);
    if (Number(currentInfo.code) !== 0 || currentInfo.data.user_id !== username || currentInfo.data.location !== location) {
      throw new Error(`rotated token is not authoritative: ${JSON.stringify(currentInfo)}`);
    }

    fs.writeFileSync(disconnectMarker, `${Date.now()}\n`);
    const disconnectDeadline = Date.now() + 60000;
    while (fs.existsSync(disconnectMarker) && Date.now() < disconnectDeadline) {
      await page.waitForTimeout(250);
    }
    if (fs.existsSync(disconnectMarker)) throw new Error('host did not trigger the websocket disconnect');
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
    if (fs.existsSync(disconnectMarker)) fs.unlinkSync(disconnectMarker);
    await context.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
