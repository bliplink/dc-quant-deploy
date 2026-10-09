// Browser-level platform approval workflow on synthetic test applications.
// Does not approve real tenants or change the live cluster topology.
const {chromium,request}=require('playwright');
const assert=(condition,msg)=>{if(!condition)throw new Error(msg)};
const base=process.env.PLATFORM_CONSOLE_BASE_URL||'http://127.0.0.1:18090';
const identity=process.env.PLATFORM_ADMIN_USERNAME,secret=process.env.PLATFORM_ADMIN_PASSWORD;
if(!identity||!secret)throw new Error('platform credentials not present in private runner environment');
const unique=String(Date.now())+'_'+Math.random().toString(36).slice(2,7);
async function call(api,method,content,token){
 const res=await api.post('/httpapi/',{headers:{'Content-Type':'application/json',...(token?{'sessionId':token}:{})},
 data:{serverName:'ManagerSvr',method,content}});
 assert(res.ok(),method+' HTTP '+res.status());
 const body=await res.json();
 assert(body.code===0,method+' '+String(body.msg||'API error').slice(0,130));
 return body.data;
}
(async()=>{
 const api=await request.newContext({baseURL:base}),browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto(base,{waitUntil:'domcontentloaded'});
 await page.getByLabel('运营账号').fill(identity);
 await page.getByLabel('密码').fill(secret);
 await page.getByRole('button',{name:'登录平台'}).click();
 await page.getByRole('heading',{name:'租户审批'}).waitFor({timeout:25000});
 const token=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('dc-platform-admin-session')||'{}').token);
 assert(token,'missing authenticated session token');
 console.log('PLATFORM_LOGIN_PASS');
 for(const [kind,label,button,expect] of [
    ['INFO','补充资料','补充资料','NEEDS_INFO'],
    ['REJECT','拒绝','拒绝','REJECTED']]){
   const tenantCode=('QAM'+kind+unique).replace(/[^a-zA-Z0-9]/g,'').slice(0,22);
   const organization='QA Mobile '+kind+' '+unique;
   const submitted=await call(api,'tenantApplication',{
     action:'SUBMIT',cid:'QA_APP_'+tenantCode,request_id:'QA_APP_'+tenantCode,
     tenant_code:tenantCode,organization_name:organization,
     contact_name:'QA Automated Verification',
     contact_email:tenantCode.toLowerCase()+'@example.invalid',
     expected_users:2,requested_symbols:['BTCUSDT'],requested_trial_days:7
   });
   assert(submitted?.application_id,'synthetic application submit returned no id');
   await page.getByRole('button',{name:'刷新'}).click();
   const row=page.locator('tbody tr').filter({hasText:organization});
   await row.waitFor({timeout:30000});
   await row.getByRole('button',{name:'审核'}).click();
   await page.getByLabel('审核意见').fill('QA acceptance '+kind);
   await page.locator('.modal').getByRole('button',{name:button,exact:true}).click();
   await row.waitFor({state:'detached',timeout:20000});
   const verified=await call(api,'tenantApproval',{
     action:'LIST',cid:'QA_VERIFY_'+tenantCode,status:expect,
     page_num:0,page_size:200
   },token);
   assert(Array.isArray(verified)&&verified.some(x=>x.application_id===submitted.application_id),
     'status '+expect+' was not persisted');
   console.log('PLATFORM_APPLICATION_'+expect+'_PASS');
 }
 await page.getByRole('button',{name:'租户管理'}).click();
 await page.getByRole('heading',{name:'租户管理'}).waitFor();
 const target=process.env.QA_TENANT_LOCATION;
 assert(target,'isolated QA tenant location missing');
 const row=page.locator('tbody tr').filter({hasText:target});
 await row.waitFor({timeout:30000});
 await row.getByRole('button',{name:'管理'}).click();
 const original=await page.getByLabel('租户名称').inputValue();
 const trial=original+' QA-verified';
 await page.getByLabel('租户名称').fill(trial);
 await page.getByRole('button',{name:'保存租户配置'}).click();
 await page.getByText(target+' 已更新',{exact:true}).waitFor({timeout:30000});
 console.log('PLATFORM_QA_TENANT_UPDATE_PASS');
 const newRow=page.locator('tbody tr').filter({hasText:target});
 await newRow.getByRole('button',{name:'管理'}).click();
 await page.getByLabel('租户名称').fill(original);
 await page.getByRole('button',{name:'保存租户配置'}).click();
 await page.getByText(target+' 已更新',{exact:true}).waitFor({timeout:30000});
 console.log('PLATFORM_QA_TENANT_RESTORE_PASS');
 await page.getByRole('button',{name:'集群管理'}).click();
 await page.getByRole('heading',{name:'集群管理'}).waitFor();
 assert(!errors.length,'page errors: '+errors.join(' | '));
 console.log('PLATFORM_CLUSTER_READONLY_PASS');
 console.log('PLATFORM_APPROVAL_ACCEPTANCE_PASS');
 }finally{await page.close();await browser.close();await api.dispose();}
})().catch(e=>{console.error('PLATFORM_APPROVAL_ACCEPTANCE_FAIL',e.message);process.exit(1)});
