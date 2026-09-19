const fs = require('fs');
const path = require('path');
const {chromium, request} = require('playwright');

const tenantBaseUrl = process.env.TENANT_CONSOLE_BASE_URL || 'http://127.0.0.1:18092';
const platformBaseUrl = process.env.PLATFORM_CONSOLE_BASE_URL || 'http://127.0.0.1:18090';
const locationA = process.env.E2E_LOCATION_A;
const locationB = process.env.E2E_LOCATION_B;
const adminUser = process.env.E2E_ADMIN_USER || 'tenantadmin';
const adminPasswordB = process.env.E2E_ADMIN_PASSWORD_B;
const sharedUser = process.env.E2E_SHARED_USER || 'sharedtrader';
const traderPasswordB = process.env.E2E_TRADER_PASSWORD_B;
const platformUser = process.env.PLATFORM_ADMIN_USERNAME;
const platformPassword = process.env.PLATFORM_ADMIN_PASSWORD;
const suffix = String(process.env.E2E_SUFFIX || Date.now()).replace(/[^A-Za-z0-9]/g, '').slice(-12);
const artifactDir = process.env.E2E_ARTIFACT_DIR || '/artifacts/standalone-consoles';

for (const [name, value] of Object.entries({
  locationA, locationB, adminPasswordB, traderPasswordB, platformUser, platformPassword
})) {
  if (!value) throw new Error(`${name} is required`);
}
fs.mkdirSync(artifactDir, {recursive: true});

const screenshot = (page, name) => page.screenshot({path: path.join(artifactDir, name), fullPage: true});

async function gatewayCall(api, serverName, method, content, token) {
  const response = await api.post('/httpapi', {
    headers: {'Content-Type': 'application/json', ...(token ? {sessionId: token} : {})},
    data: {serverName, method, content}
  });
  if (!response.ok()) throw new Error(`${serverName}.${method} HTTP ${response.status()}`);
  const body = await response.json();
  if (Number(body.code) !== 0) throw new Error(`${serverName}.${method} failed: ${JSON.stringify(body)}`);
  return body.data === undefined ? body : body.data;
}

async function loginApi(api, username, password, location, clientType = 'WEB') {
  return gatewayCall(api, 'LoginSvr', 'SYS.ATS.LOGIN', {
    method: 'login',
    cid: `CONSOLE_E2E_LOGIN_${username}_${suffix}`,
    user_id: username,
    user_name: username,
    password,
    client_type: clientType,
    Location: location
  });
}

async function tenantConsoleLogin(page) {
  await page.goto(`${tenantBaseUrl}/?location=${encodeURIComponent(locationB)}`, {waitUntil: 'domcontentloaded'});
  await page.getByText('Tenant Console', {exact: true}).waitFor({timeout: 30000});
  await page.getByLabel('租户管理员账号').fill(adminUser);
  await page.getByLabel('密码').fill(adminPasswordB);
  await page.getByRole('button', {name: '登录租户控制台'}).click();
  await page.getByRole('heading', {name: '租户工作台'}).waitFor({timeout: 60000});
  const session = await page.evaluate(() => JSON.parse(sessionStorage.getItem('dc-tenant-admin-session') || '{}'));
  if (session.location !== locationB || session.client_type !== 'TenantAdmin') {
    throw new Error(`standalone tenant session mismatch: ${JSON.stringify(session)}`);
  }
  return session;
}

async function tenantUsers(page, api) {
  await page.getByRole('button', {name: '用户管理'}).click();
  await page.getByRole('heading', {name: '用户管理'}).waitFor();

  const username = `uiuser_${suffix.toLowerCase()}`.slice(0, 32);
  const originalPassword = `UiPass!${suffix}A1`;
  const resetPassword = `UiReset!${suffix}B2`;

  await page.getByRole('button', {name: '新增用户'}).click();
  await page.getByLabel('用户名').fill(username);
  await page.getByLabel('初始密码').fill(originalPassword);
  await page.getByLabel('姓名').fill('Console Acceptance User');
  await page.getByLabel('邮箱').fill(`${username}@acceptance.invalid`);
  await page.getByRole('button', {name: '创建用户'}).click();
  await page.getByText('用户已创建', {exact: true}).waitFor({timeout: 30000});

  let row = page.locator('tbody tr').filter({hasText: username});
  await row.waitFor({timeout: 30000});
  await row.getByRole('button', {name: '禁用'}).click();
  await row.getByText('DISABLED', {exact: true}).waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: username});
  await row.getByRole('button', {name: '启用'}).click();
  await row.getByText('ENABLED', {exact: true}).waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: username});
  await row.getByRole('button', {name: '重置密码'}).click();
  await page.getByLabel('新密码').fill(resetPassword);
  await page.getByRole('button', {name: '确认重置'}).click();
  await page.getByText('密码已重置', {exact: true}).waitFor({timeout: 30000});

  const identity = await loginApi(api, username, resetPassword, locationB, 'WEB');
  if (!identity.user_id || identity.location !== locationB) {
    throw new Error(`reset-password login did not return the expected tenant identity: ${JSON.stringify(identity)}`);
  }
  return {username, userId: identity.user_id};
}

async function tenantTrading(page) {
  await page.getByRole('button', {name: '交易查询'}).click();
  await page.getByRole('heading', {name: '交易查询'}).waitFor();
  for (const tab of ['委托', '成交', '持仓', '余额']) {
    await page.getByRole('button', {name: tab, exact: true}).click();
    await page.waitForTimeout(300);
    if (await page.locator('.error.banner').count()) {
      throw new Error(`tenant trading tab ${tab} returned an error: ${await page.locator('.error.banner').innerText()}`);
    }
  }
  await page.getByRole('button', {name: '刷新'}).click();
}

async function tenantSymbols(page) {
  await page.getByRole('button', {name: '品种管理'}).click();
  await page.getByRole('heading', {name: '品种管理'}).waitFor();
  let row = page.locator('tbody tr').filter({hasText: 'BTCUSDT'});
  await row.waitFor({timeout: 30000});
  const originalAction = (await row.locator('button').innerText()).trim();
  page.once('dialog', dialog => dialog.accept());
  await row.locator('button').click();
  await page.locator('.success.banner').waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: 'BTCUSDT'});
  const restoreAction = originalAction === '禁用' ? '启用' : '禁用';
  await row.getByRole('button', {name: restoreAction}).waitFor();
  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button', {name: restoreAction}).click();
  await page.locator('.success.banner').waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: 'BTCUSDT'});
  const finalAction = (await row.locator('button').innerText()).trim();
  if (finalAction !== originalAction) throw new Error(`BTCUSDT state was not restored: ${originalAction} -> ${finalAction}`);
}

async function tenantRobot(page, api) {
  const trader = await loginApi(api, sharedUser, traderPasswordB, locationB, 'WEB');
  const apiKeyData = await gatewayCall(api, 'LoginSvr', 'updateApiKey', {
    cid: `CONSOLE_ROBOT_KEY_${suffix}`,
    type: 'trade',
    inf1: 'Standalone Tenant Web acceptance'
  }, trader.token || trader.sid);
  const apiKey = apiKeyData.api_key;
  if (!apiKey || !trader.user_id) throw new Error('could not create Robot API credential fixture');

  await page.getByRole('button', {name: 'Robot 管理'}).click();
  await page.getByRole('heading', {name: 'Robot 管理'}).waitFor();
  const robotName = `UI Robot ${suffix}`;
  const editedName = `${robotName} Edited`;

  await page.getByRole('button', {name: '新增 Robot'}).click();
  await page.getByLabel('Robot 名称').fill(robotName);
  await page.getByLabel('品种').fill('BTCUSDT');
  await page.getByLabel('API 用户').fill(String(trader.user_id));
  await page.getByLabel('API Key').fill(apiKey);
  await page.getByLabel('Order Qty').fill('0.001');
  await page.getByLabel('Max Position Qty').fill('1');
  await page.getByRole('button', {name: '保存 Robot'}).click();
  await page.getByText('Robot 已创建。', {exact: true}).waitFor({timeout: 30000});

  let row = page.locator('tbody tr').filter({hasText: robotName});
  await row.waitFor({timeout: 30000});
  await row.getByRole('button', {name: '编辑'}).click();
  await page.getByLabel('Robot 名称').fill(editedName);
  await page.getByLabel('API Key').fill(apiKey);
  await page.getByRole('button', {name: '保存 Robot'}).click();
  await page.getByText('Robot 配置已更新，运行状态已重置为 STOPPED。', {exact: true}).waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: editedName});
  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button', {name: '启用'}).click();
  await page.locator('.success.banner').waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: editedName});
  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button', {name: '禁用'}).click();
  await page.locator('.success.banner').waitFor({timeout: 30000});
}

async function tenantInfoAuditSettings(page) {
  await page.getByRole('button', {name: '租户信息'}).click();
  await page.getByRole('heading', {name: '租户信息'}).waitFor();
  await page.getByText(locationB, {exact: true}).first().waitFor();

  await page.getByRole('button', {name: '审计日志'}).click();
  await page.getByRole('heading', {name: '审计日志'}).waitFor();
  const auditRows = page.locator('.table-card tbody tr');
  await auditRows.first().waitFor({timeout: 30000});
  if (await auditRows.count() < 1) throw new Error('tenant audit log is empty after management mutations');

  await page.getByRole('button', {name: '系统设置'}).click();
  await page.getByRole('heading', {name: '系统设置'}).waitFor();

  const reg = page.getByLabel('允许用户注册');
  const trade = page.getByLabel('允许交易');
  const locale = page.getByLabel('默认语言');
  const branding = page.getByLabel('Branding JSON');
  const original = {
    registration: await reg.isChecked(),
    trade: await trade.isChecked(),
    locale: await locale.inputValue(),
    branding: await branding.inputValue()
  };
  const alternateLocale = original.locale === 'zh-CN' ? 'en-US' : 'zh-CN';
  await locale.selectOption(alternateLocale);
  await branding.fill(JSON.stringify({name: `Acceptance-${suffix}`}));
  await page.getByRole('button', {name: '保存设置'}).click();
  await page.getByText('设置已保存', {exact: true}).waitFor({timeout: 30000});

  if ((await reg.isChecked()) !== original.registration) await reg.click();
  if ((await trade.isChecked()) !== original.trade) await trade.click();
  await locale.selectOption(original.locale);
  await branding.fill(original.branding);
  await page.getByRole('button', {name: '保存设置'}).click();
  await page.getByText('设置已保存', {exact: true}).waitFor({timeout: 30000});
}

async function tenantLogout(page) {
  await page.locator('aside footer').getByRole('button', {name: '退出'}).click();
  await page.getByText('Tenant Console', {exact: true}).waitFor({timeout: 30000});
  const session = await page.evaluate(() => sessionStorage.getItem('dc-tenant-admin-session'));
  if (session) throw new Error('tenant console logout left a session behind');
}

async function submitApplication(api, kind) {
  const compact = (`${kind}${suffix}`).replace(/[^A-Za-z0-9]/g, '').slice(0, 24);
  const email = `${compact.toLowerCase()}@acceptance.invalid`;
  const data = await gatewayCall(api, 'ManagerSvr', 'tenantApplication', {
    action: 'SUBMIT',
    cid: `UI_APP_${compact}`,
    request_id: `UI_APP_${compact}`,
    tenant_code: compact,
    organization_name: `UI ${kind} ${suffix}`,
    contact_name: 'Console Acceptance',
    contact_email: email,
    expected_users: 3,
    requested_symbols: ['BTCUSDT'],
    requested_trial_days: 30
  });
  return {kind, email, organization: `UI ${kind} ${suffix}`, applicationId: data.application_id};
}

async function platformConsoleLogin(page) {
  await page.goto(platformBaseUrl, {waitUntil: 'domcontentloaded'});
  await page.getByText('Platform Operations', {exact: true}).waitFor({timeout: 30000});
  await page.getByLabel('运营账号').fill(platformUser);
  await page.getByLabel('密码').fill(platformPassword);
  await page.getByRole('button', {name: '登录平台'}).click();
  await page.getByRole('heading', {name: '租户审批'}).waitFor({timeout: 60000});
  const session = await page.evaluate(() => JSON.parse(sessionStorage.getItem('dc-platform-admin-session') || '{}'));
  if (session.location !== 'PLATFORM') throw new Error(`platform session mismatch: ${JSON.stringify(session)}`);
  return session;
}

async function platformApplications(page, api, platformToken) {
  const needsInfo = await submitApplication(api, 'NEEDS');
  const rejected = await submitApplication(api, 'REJECT');
  const approved = await submitApplication(api, 'APPROVE');
  await page.getByRole('button', {name: '刷新'}).click();

  async function review(app, action, comment) {
    const row = page.locator('tbody tr').filter({hasText: app.organization});
    await row.waitFor({timeout: 30000});
    await row.getByRole('button', {name: '审核'}).click();
    await page.getByLabel('审核意见').fill(comment);
    if (action === 'APPROVE') {
      await page.getByLabel('管理员初始密码').fill(`Admin!${suffix}A1`);
      await page.getByRole('button', {name: '批准并开通'}).click();
    } else if (action === 'NEEDS_INFO') {
      await page.getByRole('button', {name: '补充资料'}).click();
    } else {
      await page.getByRole('button', {name: '拒绝'}).click();
    }
    await row.waitFor({state: 'detached', timeout: 30000}).catch(() => {});
  }

  await review(needsInfo, 'NEEDS_INFO', 'Need more acceptance information');
  await review(rejected, 'REJECT', 'Acceptance rejection path');
  await review(approved, 'APPROVE', 'Acceptance approval path');

  for (const [app, status] of [[needsInfo, 'NEEDS_INFO'], [rejected, 'REJECTED'], [approved, 'APPROVED']]) {
    const list = await gatewayCall(api, 'ManagerSvr', 'tenantApproval', {
      action: 'LIST', cid: `VERIFY_${status}_${suffix}`, status, page_num: 0, page_size: 200
    }, platformToken);
    if (!(list || []).some(row => row.application_id === app.applicationId)) {
      throw new Error(`platform UI did not move ${app.applicationId} to ${status}`);
    }
  }
}

async function platformTenants(page) {
  await page.getByRole('button', {name: '租户管理'}).click();
  await page.getByRole('heading', {name: '租户管理'}).waitFor();
  let row = page.locator('tbody tr').filter({hasText: locationB});
  await row.waitFor({timeout: 30000});
  await row.getByRole('button', {name: '管理'}).click();

  const nameInput = page.getByLabel('租户名称');
  const originalName = await nameInput.inputValue();
  const registration = page.getByLabel('允许注册');
  const originalRegistration = await registration.isChecked();
  await nameInput.fill(`${originalName} UI`);
  await registration.setChecked(!originalRegistration);

  const routeRow = page.locator('.route-editor tbody tr').first();
  await routeRow.waitFor({timeout: 30000});
  await routeRow.getByRole('button', {name: '保存'}).click();
  await page.locator('.success.banner').waitFor({timeout: 30000});

  await page.getByRole('button', {name: '保存租户配置'}).click();
  await page.getByText(`${locationB} 已更新`, {exact: true}).waitFor({timeout: 30000});

  row = page.locator('tbody tr').filter({hasText: locationB});
  await row.getByRole('button', {name: '管理'}).click();
  await nameInput.fill(originalName);
  const registration2 = page.getByLabel('允许注册');
  if ((await registration2.isChecked()) !== originalRegistration) await registration2.click();
  await page.getByRole('button', {name: '保存租户配置'}).click();
  await page.getByText(`${locationB} 已更新`, {exact: true}).waitFor({timeout: 30000});
}

async function platformCluster(page) {
  await page.getByRole('button', {name: '集群管理'}).click();
  await page.getByRole('heading', {name: '集群管理'}).waitFor({timeout: 30000});
  for (const service of ['OrderSvr', 'MDSvr', 'TradeSvr']) {
    await page.locator('.section-head select').selectOption(service);
    await page.getByRole('button', {name: '刷新拓扑'}).click();
    await page.getByText(service, {exact: true}).first().waitFor({timeout: 30000});
  }

  const serviceSelects = page.locator('.editor select');
  await serviceSelects.first().selectOption('OrderSvr');
  const textarea = page.locator('.editor textarea');
  await textarea.waitFor({timeout: 30000});
  const catalog = (await textarea.inputValue()).trim();
  if (!catalog) throw new Error('OrderSvr has no placement catalog to safely re-apply');

  await page.getByRole('button', {name: '校验并预览'}).click();
  await page.getByText('预览通过', {exact: true}).waitFor({timeout: 30000});
  page.once('dialog', dialog => dialog.accept());
  await page.locator('.editor').getByRole('button', {name: /^发布 v/}).click();
  await page.getByText(/OrderSvr Placement 已发布/).waitFor({timeout: 30000});

  for (const name of ['新增节点', '滚动升级', '回滚版本']) {
    const button = page.getByRole('button', {name});
    if (!(await button.isDisabled())) throw new Error(`${name} must remain disabled until the host Agent exists`);
  }
}

async function platformLogout(page) {
  await page.locator('aside footer').getByRole('button', {name: '退出'}).click();
  await page.getByText('Platform Operations', {exact: true}).waitFor({timeout: 30000});
  const session = await page.evaluate(() => sessionStorage.getItem('dc-platform-admin-session'));
  if (session) throw new Error('platform console logout left a session behind');
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const tenantApi = await request.newContext({baseURL: tenantBaseUrl});
  const platformApi = await request.newContext({baseURL: platformBaseUrl});
  const tenantContext = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const platformContext = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const tenantPage = await tenantContext.newPage();
  const platformPage = await platformContext.newPage();
  const pageErrors = [];
  for (const page of [tenantPage, platformPage]) page.on('pageerror', error => pageErrors.push(error.message));

  try {
    await tenantConsoleLogin(tenantPage);
    await tenantUsers(tenantPage, tenantApi);
    await tenantTrading(tenantPage);
    await tenantSymbols(tenantPage);
    await tenantRobot(tenantPage, tenantApi);
    await tenantInfoAuditSettings(tenantPage);
    await screenshot(tenantPage, 'standalone-tenant-console.png');
    await tenantLogout(tenantPage);

    const platformSession = await platformConsoleLogin(platformPage);
    await platformApplications(platformPage, platformApi, platformSession.token || platformSession.sid);
    await platformTenants(platformPage);
    await platformCluster(platformPage);
    await screenshot(platformPage, 'standalone-platform-console.png');
    await platformLogout(platformPage);

    if (pageErrors.length) throw new Error(`page errors: ${pageErrors.join(' | ')}`);
    console.log(JSON.stringify({
      status: 'PASS',
      tenant: {baseUrl: tenantBaseUrl, location: locationB},
      platform: {baseUrl: platformBaseUrl},
      covered: [
        'tenant-login-session', 'tenant-users-create-disable-enable-reset', 'tenant-trading-tabs',
        'tenant-symbol-disable-enable', 'tenant-robot-create-edit-enable-disable',
        'tenant-info-audit-settings-restore', 'tenant-logout',
        'platform-login', 'applications-needs-info-reject-approve', 'tenant-update-route-restore',
        'cluster-snapshot-preview-apply', 'disabled-agent-actions', 'platform-logout'
      ],
      screenshots: fs.readdirSync(artifactDir).sort()
    }));
  } finally {
    await tenantApi.dispose();
    await platformApi.dispose();
    await tenantContext.close();
    await platformContext.close();
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
