/* Real Chromium acceptance of signed-in tenant/platform management on phones,
   tablets and desktop. Only the isolated QA tenant is modified. */
const fs = require('fs');
const {chromium, request} = require('playwright');

const tenantURL = process.env.TENANT_CONSOLE_BASE_URL || 'http://127.0.0.1:18092';
const platformURL = process.env.PLATFORM_CONSOLE_BASE_URL || 'http://127.0.0.1:18090';
const outDir = '/artifacts/management-qa-20261009';
const loc = process.env.QA_TENANT_LOCATION;
for (const key of ['QA_TENANT_LOCATION','QA_ADMIN_USERNAME','QA_ADMIN_PASSWORD','PLATFORM_ADMIN_USERNAME','PLATFORM_ADMIN_PASSWORD']) {
 if (!process.env[key]) throw new Error('missing required QA environment: '+key);
}
fs.mkdirSync(outDir,{recursive:true});
const results=[];
const assert=(v,m)=>{if(!v) throw new Error(m)};
const isMobile=w=>w<=1024;
async function record(page,area,view,width,errors) {
 const metrics=await page.evaluate(()=>{
 const c=s=>document.querySelector(s);
 const style=el=>el?getComputedStyle(el):null;
 const width=window.innerWidth, doc=document.documentElement.scrollWidth;
 const table=c('.table-card');
 return {width,doc,bodyFont:style(document.body)?.fontFamily,
  headingFont:style(c('h1'))?.fontSize,
  navFont:style(c('.app-shell nav button'))?.fontSize,
  navButtonHeight:Math.round(c('.app-shell nav button')?.getBoundingClientRect().height||0),
  tabularOverflow:table?table.scrollWidth>table.clientWidth:false,
  outsideElements:[...document.querySelectorAll('body *')].filter(e=>{
    const r=e.getBoundingClientRect();
    return r.width>0&&r.right>width+8&&style(e)?.position!=='fixed';
  }).slice(0,4).map(e=>e.tagName+'.'+String(e.className).slice(0,32))};
 });
 assert(metrics.doc<=width+1,area+' '+view+' width='+width+' overflows: '+JSON.stringify(metrics));
 if(isMobile(width))assert(metrics.navButtonHeight>=43,area+' mobile nav is too small');
 const bad=await page.locator('.error.banner').allInnerTexts();
 assert(bad.length===0,area+' '+view+' UI error: '+bad.join(' | ').slice(0,180));
 assert(errors.length===0,area+' '+view+' JS errors: '+errors.join(' | ').slice(0,130));
 const path=outDir+'/'+area+'-'+view+'-'+width+'.png';
 await page.screenshot({path,fullPage:false});
 results.push({area,view,...metrics,screenshot:path.replace('/artifacts/','')});
 console.log('MOBILE_QA_PASS',area,view,width,'doc',metrics.doc,'heading',metrics.headingFont,'font',metrics.bodyFont?.split(',')[0]);
}
async function tenantLogin(page) {
 await page.goto(tenantURL+'/?location='+loc,{waitUntil:'domcontentloaded',timeout:28000});
 await page.getByRole('button',{name:'中文'}).click();
 await page.getByLabel('管理员账号').fill(process.env.QA_ADMIN_USERNAME);
 await page.getByLabel('密码').fill(process.env.QA_ADMIN_PASSWORD);
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.getByRole('heading',{name:'租户工作台'}).waitFor({timeout:40000});
}
async function platformLogin(page){
 await page.goto(platformURL,{waitUntil:'domcontentloaded',timeout:27000});
 await page.getByLabel('运营账号').fill(process.env.PLATFORM_ADMIN_USERNAME);
 await page.getByLabel('密码').fill(process.env.PLATFORM_ADMIN_PASSWORD);
 await page.getByRole('button',{name:'登录平台'}).click();
 await page.getByRole('heading',{name:'租户审批'}).waitFor({timeout:40000});
}
async function inspectRole(browser,area,width){
 const page=await browser.newPage({viewport:{width,height:844}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e).slice(0,200)));
 try {
  if(area==='tenant'){
   await tenantLogin(page);
   const views=[['dashboard','租户工作台'],['users','用户管理'],['trading','交易查询'],['symbols','品种管理'],['robots','Robot 管理'],['info','租户信息'],['audit','审计日志'],['settings','系统设置']];
   for(const [name,title] of views){
    if(name!=='dashboard')await page.locator('.app-shell nav').getByRole('button',{name:title,exact:true}).click();
    await page.getByRole('heading',{name:title,exact:true}).waitFor({timeout:24000});
    await page.waitForTimeout(750);
    await record(page,area,name,width,errors);
   }
  }else{
   await platformLogin(page);
   const views=[['applications','租户审批'],['tenants','租户管理'],['cluster','集群管理']];
   for(const [name,title] of views){
    if(name!=='applications')await page.locator('.app-shell nav').getByRole('button',{name:title,exact:true}).click();
    await page.getByRole('heading',{name:title,exact:true}).waitFor({timeout:28000});
    await page.waitForTimeout(950);
    await record(page,area,name,width,errors);
   }
  }
 }finally { await page.close(); }
}
async function tenantUserCRUD(browser){
 const page=await browser.newPage({viewport:{width:390,height:844}});
 const api=await request.newContext({baseURL:tenantURL});
 let name;
 const pass='UiTesting'+Date.now()+'!A';
 const updated='Updated'+Date.now()+'!B';
 try{
  await tenantLogin(page);
  await page.locator('.app-shell nav').getByRole('button',{name:'用户管理'}).click();
  await page.getByRole('heading',{name:'用户管理'}).waitFor();
  // The user list fetch is asynchronous: wait before deciding to create.
  await page.locator('tbody tr').first().waitFor({timeout:30000});
  let row=page.locator('tbody tr').filter({hasText:'qa_ui_'}).first();
  if(await row.count()){
    name=(await row.innerText()).match(/qa_ui_[a-zA-Z0-9]+/)[0];
    console.log('CRUD_REUSE_EXISTING_TEST_USER');
  }else{
    name='qa_ui_'+String(Date.now()).slice(-9);
    await page.getByRole('button',{name:'新增用户'}).click();
    await page.getByLabel('用户名').fill(name);
    await page.getByLabel('初始密码').fill(pass);
    await page.getByLabel('姓名').fill('Mobile QA User');
    await page.getByLabel('邮箱').fill(name+'@example.invalid');
    await page.getByRole('button',{name:'创建用户'}).click();
    await page.getByText('用户已创建',{exact:true}).waitFor({timeout:30000});
    row=page.locator('tbody tr').filter({hasText:name});
    await row.waitFor({timeout:30000});
    console.log('CRUD_CREATE_PASS');
  }
  if(await row.getByRole('button',{name:'禁用'}).count()){
    await row.getByRole('button',{name:'禁用'}).click();
    await row.getByText('DISABLED',{exact:true}).first().waitFor({timeout:30000});
  }else await row.getByText('DISABLED',{exact:true}).first().waitFor();
  console.log('CRUD_DISABLE_PASS');
  row=page.locator('tbody tr').filter({hasText:name});
  await row.getByRole('button',{name:'启用'}).click();
  await row.getByText('ENABLED',{exact:true}).first().waitFor({timeout:30000});
  console.log('CRUD_ENABLE_PASS');
  row=page.locator('tbody tr').filter({hasText:name});
  await row.getByRole('button',{name:'重置密码'}).click();
  await page.getByLabel('新密码').fill(updated);
  await page.getByRole('button',{name:'确认重置'}).click();
  await page.getByText('密码已重置',{exact:true}).waitFor({timeout:30000});
  console.log('CRUD_RESET_PASSWORD_PASS');
  const response=await api.post('/httpapi/',{headers:{'Content-Type':'application/json'},data:{
    serverName:'LoginSvr',method:'SYS.ATS.LOGIN',content:{method:'login',cid:'QA_RESET_LOGIN_'+Date.now(),
    user_id:name,user_name:name,password:updated,client_type:'WEB',Location:loc}}});
  const body=await response.json();
  assert(Number(body.code)===0 && !!body.data?.token,'user cannot log in after password reset');
  console.log('CRUD_UPDATED_LOGIN_PASS');
  await record(page,'tenant','user-crud',390,[]);
 }finally{
   await api.dispose();
   await page.close();
 }
}
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
 if(process.env.QA_ONLY_CRUD!=='1'){
  for(const width of [390,768,1366]){
   for(const area of ['tenant','platform']) await inspectRole(browser,area,width);
  }
 }
 if(process.env.QA_ONLY_UI!=='1') await tenantUserCRUD(browser);
 fs.writeFileSync(outDir+'/qa-results.json',JSON.stringify({result:'PASS',tenant:loc,results},null,2));
 if(fs.existsSync(outDir+'/qa-failure.txt')) fs.unlinkSync(outDir+'/qa-failure.txt');
 console.log('MANAGEMENT_MOBILE_QA_PASS pages='+results.length+' location='+loc);
 }finally{ await browser.close(); }
})().catch(e=>{
 fs.writeFileSync(outDir+'/qa-failure.txt',String(e.stack||e.message));
 console.error('MANAGEMENT_MOBILE_QA_FAIL',e.stack||e.message);process.exit(1);
});
