// Isolated QA Robot browser STOP -> START acceptance (no key creation/rotation).
const {chromium,request}=require('playwright');
const loc=process.env.QA_TENANT_LOCATION;
const tenantURL=process.env.TENANT_CONSOLE_BASE_URL||'http://127.0.0.1:18092';
const uid=process.env.QA_ADMIN_USERNAME,pwd=process.env.QA_ADMIN_PASSWORD;
if(!loc||!uid||!pwd) throw new Error('QA tenant credentials missing');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ensure=(a,m)=>{if(!a)throw new Error(m)};
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const api=await request.newContext({baseURL:tenantURL});
 const page=await browser.newPage({viewport:{width:390,height:844}});
 let token=null,robotID=null,stopped=false,restored=false;
 const gateway=async(serverName,method,content)=>{
   const res=await api.post('/httpapi/',{headers:{'Content-Type':'application/json',...(token?{sessionId:token}:{})},
     data:{serverName,method,content}});
   const body=await res.json();if(body.code!==0)throw new Error(method+': '+String(body.msg).slice(0,150));
   return body.data;
 };
 const list=async()=>await gateway('AdminSvr','tenantRobotAdmin',{action:'LIST',cid:'ROBOT_QA_LIST_'+Date.now()});
 const runtime=async()=>{
  const data=await gateway('ManagerSvr','robotMonitor',{action:'LIST',cid:'ROBOT_QA_RUNTIME_'+Date.now(),robot_id:robotID,page_num:0,page_size:10});
  return (data?.items||[]).find(x=>x.robot_id===robotID);
 };
 const control=async(action)=>await gateway('ManagerSvr','robotControl',{
   action,robot_id:robotID,cid:'ROBOT_QA_'+action+'_'+Date.now(),request_id:'ROBOT_QA_'+action+'_'+Date.now()});
 try{
 await page.goto(tenantURL+'/?location='+loc,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'中文'}).click();
 await page.getByLabel('管理员账号').fill(uid);
 await page.getByLabel('密码').fill(pwd);
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.getByRole('heading',{name:'租户工作台'}).waitFor({timeout:25000});
 token=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('dc-tenant-admin-session')||'{}').token);
 ensure(token,'QA login no token');
 await page.locator('.app-shell nav').getByRole('button',{name:'Robot 管理'}).click();
 await page.getByRole('heading',{name:'Robot 管理'}).waitFor({timeout:20000});
 const before=await list();ensure(Array.isArray(before),'missing robot list');
 const robot=before.find(x=>x.enabled && x.security_id==='BTCUSDT');
 ensure(robot,'no active isolated QA BTCUSDT Robot');
 robotID=robot.robot_id;
 const row=page.locator('tbody tr').filter({hasText:robot.robot_name});
 for(let i=0;i<4;i++){
   try{await row.waitFor({timeout:7000});break}
   catch(err){
     const message=await page.locator('.error.banner').allInnerTexts();
     console.log('ROBOT_UI_RETRY',i+1,message.map(x=>x.slice(0,130)).join('|'));
     await page.getByRole('button',{name:'刷新',exact:true}).first().click();
   }
 }
 await row.waitFor({timeout:9000});
 await row.getByRole('button',{name:'详情'}).click();
 await page.locator('.robot-detail-modal').waitFor({timeout:13000});
 await page.waitForTimeout(1800);
 const detailText=await page.locator('.robot-detail-modal').innerText();
 console.log('ROBOT_DETAIL_INSPECT',detailText.replace(/\\s+/g,' ').slice(0,240));
 if(!detailText.includes('实时运行'))throw new Error('Robot detail dialog returned no operational detail');
 await page.locator('.robot-detail-modal header button').click();
 console.log('ROBOT_DETAIL_PASS');
 if(process.env.QA_DETAIL_ONLY==='1')return;
 if(process.env.QA_VERIFY_ONLY==='1'){
   const current=await runtime();
   ensure(current&&current.enabled&&current.runtime_status==='RUNNING'&&Number(current.open_order_count)>=40,
       'Robot runtime monitor did not confirm RUNNING/40 orders');
   console.log('ROBOT_RECOVERY_MONITOR_PASS');return;
 }
 page.once('dialog',d=>d.accept());
 await row.getByRole('button',{name:'停止'}).click();
 await page.locator('.success.banner').waitFor({timeout:25000});
 stopped=true;
 console.log('ROBOT_STOP_UI_PASS');
 let disabled=false;
 for(let i=0;i<15;i++){
   const current=await list();
   if(current.some(x=>x.robot_id===robotID&&!x.enabled)){disabled=true;break;}
   await sleep(1000);
 }
 ensure(disabled,'Robot was not disabled');
 console.log('ROBOT_STOP_STATE_PASS');
 // Do not bypass the current owner barrier. Allow cancellation and lease release.
 await sleep(9000);
 const startButton=page.locator('tbody tr').filter({hasText:robot.robot_name}).getByRole('button',{name:'启动'});
 await startButton.waitFor({timeout:22000});
 page.once('dialog',d=>d.accept());
 await startButton.click();
 await page.locator('.success.banner').waitFor({timeout:20000});
 console.log('ROBOT_START_UI_PASS');
 let running=false;
 for(let i=0;i<75;i++){
   const current=await runtime();
   if(current?.enabled&&current.runtime_status==='RUNNING'&&Number(current.open_order_count)>=40){
      running=true;break;
   }
   await sleep(1000);
 }
 ensure(running,'Robot did not return to RUNNING/40 orders in time');
 restored=true;
 console.log('ROBOT_RECOVERY_40_ORDERS_PASS');
 console.log('ROBOT_CONTROL_ACCEPTANCE_PASS '+loc);
 }finally{
   if(stopped&&!restored&&robotID&&token){
    // Best effort recovery; failure must stay visible and trigger manual alert.
    try{
     for(let i=0;i<4;i++){try{await control('START');console.log('ROBOT_AUTORESTORE_START_SUBMITTED');break}catch(err){if(i===3)throw err;await sleep(8000)}}
    }catch(e){console.error('ROBOT_AUTORESTORE_FAILED',e.message)}
   }
   await page.close();await api.dispose();await browser.close();
 }
})().catch(e=>{console.error('ROBOT_CONTROL_ACCEPTANCE_FAIL',e.message);process.exit(1)});
