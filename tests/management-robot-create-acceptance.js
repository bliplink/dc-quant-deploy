// Create one DISABLED Robot under the isolated QA tenant, using its already authorized QA trade identity.
// Never print or persist API key; never enable the new Robot or place orders.
const {chromium}=require('playwright');
const ensure=(v,m)=>{if(!v)throw new Error(m)};
const loc=process.env.QA_TENANT_LOCATION;
const user=process.env.QA_ROBOT_API_USER_ID, key=process.env.QA_ROBOT_API_KEY;
if(!loc||!user||!key)throw Error('missing isolated QA identity');
const name='QA Disabled Robot '+Date.now().toString().slice(-9);
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});
 try {
  await page.goto('http://127.0.0.1:18092/?location='+loc,{waitUntil:'domcontentloaded',timeout:20000});
  await page.getByRole('button',{name:'中文'}).click();
  await page.getByLabel('管理员账号').fill(process.env.QA_ADMIN_USERNAME);
  await page.getByLabel('密码').fill(process.env.QA_ADMIN_PASSWORD);
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByRole('heading',{name:'租户工作台'}).waitFor({timeout:25000});
  await page.locator('.app-shell nav').getByRole('button',{name:'Robot 管理'}).click();
  await page.getByRole('heading',{name:'Robot 管理'}).waitFor({timeout:23000});
  await page.getByRole('button',{name:'新增 Robot'}).click();
  const modal=page.locator('.modal.robot-modal');
  await modal.getByLabel('Robot 名称').fill(name);
  await modal.getByLabel('品种').fill('BTCUSDT');
  await modal.getByLabel('API 用户').fill(user);
  await modal.getByLabel('API Key',{exact:true}).fill(key);
  await modal.getByLabel('Order Qty').fill('0.001');
  await modal.getByLabel('Max Position Qty').fill('0.01');
  ensure(!(await modal.getByLabel('配置启用').isChecked()),'new QA Robot must default disabled');
  await modal.getByRole('button',{name:'保存 Robot'}).click();
  await modal.waitFor({state:'detached',timeout:33000});
  await page.getByText('Robot 已创建。',{exact:true}).waitFor({timeout:17000});
  const row=page.locator('tbody tr').filter({hasText:name});
  await row.waitFor({timeout:18000});
  ensure((await row.innerText()).includes('DISABLED'),'new QA Robot unexpectedly enabled');
  console.log('QA_ROBOT_CREATE_DISABLED_PASS location='+loc);
  await row.getByRole('button',{name:'编辑'}).click();
  const editor=page.locator('.modal.robot-modal');
  ensure(await editor.getByLabel('API Key',{exact:true}).inputValue()==='','old API key unexpectedly exposed');
  await editor.getByLabel('Level Step (bps)').fill('3');
  await editor.getByRole('button',{name:'保存 Robot'}).click();
  await editor.waitFor({state:'detached',timeout:30000});
  await page.getByText('Robot 配置已更新，运行状态已重置为 STOPPED。',{exact:true}).waitFor({timeout:15000});
  console.log('QA_ROBOT_EDIT_DISABLED_PASS');
 } catch(err){console.error('QA_ROBOT_CREATE_FAILED',err.message);process.exitCode=1}
 finally{await page.close();await browser.close();}
})();
