const fs = require('fs');
const path = require('path');
const {chromium, request} = require('playwright');

const location = process.env.ROBOT_HOT_EDIT_LOCATION || 'E2E001';
const robotId = process.env.ROBOT_HOT_EDIT_ID || 'default-depth10';
const password = process.env.ROBOT_HOT_EDIT_ADMIN_PASSWORD;
const makerPassword = process.env.ROBOT_HOT_EDIT_MAKER_PASSWORD;
const output = process.env.ROBOT_HOT_EDIT_ARTIFACT_DIR || '/artifacts/robot-hot-edit';
if (!password || !makerPassword) throw new Error('admin and maker test passwords are required');
fs.mkdirSync(output, {recursive: true});

async function call(api, serverName, method, content, token, key) {
  const response = await api.post('/httpapi/', {
    headers: {'Content-Type': 'application/json', ...(token ? {sessionId: token} : {})},
    data: {serverName, method, ...(key ? {key} : {}), content}
  });
  if (!response.ok()) throw new Error(`${serverName}.${method} HTTP ${response.status()}`);
  const body = await response.json();
  if (Number(body.code) !== 0) throw new Error(`${serverName}.${method}: ${body.msg}`);
  return body.data;
}

async function makerOrders(api, token, userId) {
  const data = await call(api, 'OrderSvr', 'queryOpenOrder', {
    securityid: 'BTCUSDT', userid: userId, Location: location
  }, token, `${location}\u001f4\u001fBTCUSDT`);
  return Array.isArray(data) ? data : [];
}

const normalize = row => Object.fromEntries(Object.entries(row).map(([key, value]) =>
  [key.toLowerCase().replaceAll('_', ''), value]));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  await page.addInitScript(() => localStorage.setItem('dc-trade-language', 'zh'));
  const api = await request.newContext({baseURL: 'http://127.0.0.1:18088'});
  try {
    await page.goto(`http://127.0.0.1:18092/?location=${location}`);
    await page.getByLabel('租户管理员账号').fill('tenantadmin');
    await page.getByLabel('密码').fill(password);
    await page.getByRole('button', {name: '登录租户控制台'}).click();
    await page.getByRole('heading', {name: '租户工作台'}).waitFor({timeout: 30000});
    await page.getByRole('button', {name: /^(Robot 管理|流动性管理)$/}).click();
    const row = page.locator('tbody tr').filter({hasText: robotId});
    await row.waitFor({timeout: 30000});
    await page.screenshot({path: path.join(output, 'before.png'), fullPage: true});

    const makerLogin = await call(api, 'LoginSvr', 'SYS.ATS.LOGIN', {
      method: 'login', cid: `ROBOT_HOT_EDIT_${Date.now()}`,
      user_id: 'demorobot', user_name: 'demorobot', password: makerPassword,
      client_type: 'WEB', Location: location
    });
    const userId = makerLogin.user_id || makerLogin.userid;
    const before = (await makerOrders(api, makerLogin.token, userId)).map(normalize);
    const beforeQty = [...new Set(before.map(order => String(order.orderqty)))];

    await row.getByRole('button', {name: '编辑'}).click();
    const modal = page.locator('.robot-modal');
    await modal.getByLabel('数量模式').selectOption('NOTIONAL_ZONES');
    await modal.getByLabel('保证金预算').fill('1800');
    await modal.getByLabel('杠杆').fill('1');
    await modal.getByLabel('各区档数').fill('3,3,4');
    await modal.getByLabel('各区金额权重').fill('2,3,5');
    await modal.getByRole('button', {name: '保存 Robot'}).click();
    try {
      await page.getByText(/^(Robot 配置已保存|做市策略已保存)；运行中的盘口会自动刷新，无需重启。$/).waitFor({timeout: 30000});
    } catch (error) {
      await page.screenshot({path: path.join(output, 'save-failed.png'), fullPage: true});
      throw new Error(`save did not complete: ${await page.locator('.error.banner').allTextContents()}`);
    }

    let after = [];
    let afterQty = [];
    for (let attempt = 0; attempt < 60; attempt++) {
      after = (await makerOrders(api, makerLogin.token, userId)).map(normalize);
      afterQty = [...new Set(after.map(order => String(order.orderqty)))];
      const bids = after.filter(order => String(order.side).toLowerCase() === 'buy').length;
      const asks = after.filter(order => String(order.side).toLowerCase() === 'sell').length;
      if (bids >= 10 && asks >= 10 && afterQty.length >= 3 && !afterQty.includes('0.001')) break;
      await sleep(2000);
    }
    if (afterQty.length < 3) throw new Error(`amount tiers did not reach live book: ${afterQty.join(',')}`);
    await page.screenshot({path: path.join(output, 'after.png'), fullPage: true});
    const evidence = {
      location, robotId, beforeOpenOrders: before.length, beforeQuantities: beforeQty,
      afterOpenOrders: after.length, afterQuantities: afterQty, checkedAt: new Date().toISOString()
    };
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(evidence, null, 2));
    process.stdout.write(JSON.stringify(evidence) + '\n');
  } finally {
    await api.dispose();
    await browser.close();
  }
})().catch(error => {console.error(error.message); process.exitCode = 1});
