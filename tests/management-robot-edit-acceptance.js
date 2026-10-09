// Isolated tenant Robot edit/revert acceptance. No API key is printed or changed.
const {chromium}=require('playwright');
const loc=process.env.QA_TENANT_LOCATION;
const base=process.env.TENANT_CONSOLE_BASE_URL||'http://127.0.0.1:18092';
const ensure=(v,msg)=>{if(!v)throw new Error(msg)};
(async()=>{
 const b=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await b.newPage({viewport:{width:390,height:844}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let initial=null,changed=false;
 const open=async()=>{
   const row=page.locator('tbody tr').filter({hasText:'Trial Liquidity BTCUSDT'});
   await row.waitFor({timeout:20000});
   await row.getByRole('button',{name:'编辑'}).click();
   await page.getByRole('heading',{name:'编辑 Robot'}).waitFor({timeout:11000});
   return page.locator('.modal.robot-modal');
 };
 const save=async(modal)=>{
   await modal.getByRole('button',{name:'保存 Robot'}).click();
   await modal.waitFor({state:'detached',timeout:30000});
   await page.getByText('Robot 配置已更新，运行状态已重置为 STOPPED。').waitFor({timeout:12000});
 };
 try{
  await page.goto(base+'/?location='+loc,{waitUntil:'domcontentloaded',timeout:19000});
  await page.getByRole('button',{name:'中文'}).click();
  await page.getByLabel('管理员账号').fill(process.env.QA_ADMIN_USERNAME);
  await page.getByLabel('密码').fill(process.env.QA_ADMIN_PASSWORD);
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByRole('heading',{name:'租户工作台'}).waitFor({timeout:25000});
  await page.locator('.app-shell nav').getByRole('button',{name:'Robot 管理'}).click();
  await page.getByRole('heading',{name:'Robot 管理'}).waitFor({timeout:22000});
  const modal=await open();
  initial=await modal.getByLabel('Refresh Interval (ms)').inputValue();
  const apiKey=await modal.getByLabel('API Key', {exact:true}).inputValue();
  ensure(!apiKey,'API Key unexpectedly rendered in plaintext');
  const tape=await modal.getByLabel('Strategy Config JSON').inputValue();
  ensure(tape.includes('tape_enabled'),'QA liquidity Robot lacks Tape config');
  ensure(!tape.includes('tape_api_key'),'Tape credential unexpectedly rendered');
  console.log('ROBOT_EDIT_MOBILE_SECRET_MASK_PASS');
  const altered=initial==='1000'?'1200':'1000';
  await modal.getByLabel('Refresh Interval (ms)').fill(altered);
  await save(modal);changed=true;
  console.log('ROBOT_EDIT_WITHOUT_OLD_KEY_PASS changed_refresh='+altered);
  const modalRestore=await open();
  ensure(await modalRestore.getByLabel('Refresh Interval (ms)').inputValue()===altered,'updated value not persisted');
  await modalRestore.getByLabel('Refresh Interval (ms)').fill(initial);
  await save(modalRestore);changed=false;
  const verifyModal=await open();
  ensure(await verifyModal.getByLabel('Refresh Interval (ms)').inputValue()===initial,'original setting not restored');
  await verifyModal.getByRole('button',{name:'取消'}).click();
  ensure(!errors.length,'browser JS error count='+errors.length);
  console.log('ROBOT_EDIT_RESTORE_PASS refresh='+initial);
 }catch(err){
  console.error('ROBOT_EDIT_ACCEPTANCE_FAIL',err.message);
  if(changed&&initial!==null){
   try{
    if(await page.locator('.modal.robot-modal').count()){
      await page.locator('.modal.robot-modal').getByRole('button',{name:'取消'}).click();
    }
    const modal=await open();
    await modal.getByLabel('Refresh Interval (ms)').fill(initial);
    await save(modal);
    console.log('ROBOT_EDIT_AUTO_RESTORE_PASS');
   }catch(e){console.error('ROBOT_EDIT_AUTO_RESTORE_FAILED',e.message)}
  }
  process.exitCode=1;
 }finally{await page.close();await b.close();}
})();
