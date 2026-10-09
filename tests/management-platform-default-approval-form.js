// Read-only browser acceptance: the platform review form must not propose
// example.com as the trading URL for newly assigned tenant locations.
// This script never submits APPROVE or modifies an application or service route.
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(process.env.PLATFORM_CONSOLE_BASE_URL||'http://127.0.0.1:18090/',{waitUntil:'domcontentloaded',timeout:23000});
  await page.getByLabel('运营账号').fill(process.env.PLATFORM_ADMIN_USERNAME);
  await page.getByLabel('密码').fill(process.env.PLATFORM_ADMIN_PASSWORD);
  await page.getByRole('button',{name:'登录平台'}).click();
  await page.getByRole('heading',{name:'租户审批'}).waitFor({timeout:29000});
  await page.waitForTimeout(1600); // allow the initial PENDING request to settle
  await page.locator('.section-head select').selectOption(''); // all statuses
  await page.getByRole('button',{name:'刷新',exact:true}).click();
  const row=page.locator('tbody tr').filter({hasText:'QA Mobile INFO'}).first();
  try{await row.waitFor({timeout:23000})}catch(err){
    const messages=await page.locator('.error.banner').allInnerTexts();
    throw new Error('No reviewable QA application: '+messages.join('|').slice(0,150));
  }
  await row.getByRole('button',{name:'审核'}).click();
  const dlg=page.locator('.modal');
  await dlg.waitFor();
  const urlInput=dlg.getByLabel('交易地址（留空按分配编号生成主站链接）');
  if(await urlInput.inputValue()!=='') throw new Error('Approval prefilled an invalid placeholder URL');
  if(await dlg.getByLabel('Location（留空自动生成 6 位）').inputValue()!=='')
    throw new Error('Approval unexpectedly preassigned a location');
  if(errors.length)throw new Error('JS errors: '+errors.length);
  await page.screenshot({path:'/artifacts/management-qa-20261009/platform-approval-default-390.png'});
  await dlg.locator('header button').click();
  console.log('PLATFORM_NEW_TENANT_DEFAULT_URL_FORM_PASS location_auto=true example_link_absent=true');
 }finally{await page.close();await browser.close()}
})().catch(e=>{console.error('PLATFORM_DEFAULT_FORM_FAIL '+e.message);process.exit(1)})
