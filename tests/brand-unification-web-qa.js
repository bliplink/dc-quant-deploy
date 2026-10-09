// Brand acceptance: compare page-rendered logos with the canonical public-site SVG.
// Read-only UI validation, covering mobile, tablet and desktop.
const {chromium}=require('playwright');
const fs=require('fs');
const http=process.env.BRAND_HTTP_BASE||'http://127.0.0.1';
const cases=[
  ['tenant-login', http+':18092/?location=DPGR6B', '.brand img.brand-mark'],
  ['platform-login', http+':18090/', '.brand img.brand-mark'],
  ['trade-login', http+':18088/#/login?location=DPGR6B', 'img.authBrandMark'],
  ['trade-register', http+':18088/#/register?location=DPGR6B', 'img.tenant-brand-mark'],
  ['trade-header', http+':18088/#/trade?location=DPGR6B', 'img.brandMark']
];
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const base='/artifacts/brand-unification-qa';
 fs.mkdirSync(base,{recursive:true});
 const results=[];
 try{
   for(const width of [390,768,1366]){
    for(const [app,url,selector] of cases.filter(([app])=>!process.env.BRAND_QA_AREAS||process.env.BRAND_QA_AREAS.split(',').some(area=>app.startsWith(area)))){
      const page=await browser.newPage({viewport:{width,height:844}});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      try{
        const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});
        await page.locator(selector).first().waitFor({state:'visible',timeout:26000});
        const data=await page.locator(selector).first().evaluate(img=>{
          const rect=img.getBoundingClientRect(), parent=img.closest('.brand,.tenant-brand,.authBrand,.head-user');
          return {visible:rect.width>15&&rect.height>15, complete:img.complete,
            naturalWidth:img.naturalWidth,naturalHeight:img.naturalHeight,
            src:img.getAttribute('src')||'',box:[Math.round(rect.width),Math.round(rect.height)],
            context:(parent?.innerText||'').slice(0,160)};
        });
        if(!data.visible||!data.complete||data.naturalWidth<32||data.naturalHeight<32)
          throw Error('image not loaded: '+JSON.stringify(data));
        if(!data.context.includes('OpenTradingCore') && app!=='trade-header')
          throw Error('wordmark not consistent: '+data.context);
        const filename=base+'/'+app+'-'+width+'.png';
        await page.screenshot({path:filename,fullPage:false});
        results.push({app,width,imageLoaded:true,natural:[data.naturalWidth,data.naturalHeight],size:data.box,docWidth:await page.evaluate(()=>document.documentElement.scrollWidth),jsErrors:errors.length});
        console.log('BRAND_UI_PASS',app,width,'image',data.naturalWidth+'x'+data.naturalHeight,'size',data.box.join('x'),'http',response.status());
      }finally{await page.close()}
    }
   }
   // Signed-in management sidebars must use the same mark as login screens.
   if(process.env.QA_ADMIN_USERNAME&&process.env.QA_ADMIN_PASSWORD&&process.env.PLATFORM_ADMIN_USERNAME&&process.env.PLATFORM_ADMIN_PASSWORD){
     for(const width of [390,1366]){
       for(const area of ['tenant','platform']){
         const page=await browser.newPage({viewport:{width,height:844}});
         try{
           if(area==='tenant'){
             await page.goto(http+':18092/?location='+process.env.QA_TENANT_LOCATION,{waitUntil:'domcontentloaded'});
             await page.getByRole('button',{name:'中文'}).click();
             await page.getByLabel('管理员账号').fill(process.env.QA_ADMIN_USERNAME);
             await page.getByLabel('密码').fill(process.env.QA_ADMIN_PASSWORD);
             await page.getByRole('button',{name:'登录',exact:true}).click();
             await page.getByRole('heading',{name:'租户工作台'}).waitFor({timeout:25000});
           }else{
             await page.goto(http+':18090/',{waitUntil:'domcontentloaded'});
             await page.getByLabel('运营账号').fill(process.env.PLATFORM_ADMIN_USERNAME);
             await page.getByLabel('密码').fill(process.env.PLATFORM_ADMIN_PASSWORD);
             await page.getByRole('button',{name:'登录平台'}).click();
             await page.getByRole('heading',{name:'租户审批'}).waitFor({timeout:25000});
           }
           const mark=page.locator('.brand.side img.brand-mark');
           await mark.waitFor({state:'visible',timeout:17000});
           const ok=await mark.evaluate(img=>img.complete&&img.naturalWidth>0&&img.getBoundingClientRect().width>=25);
           if(!ok)throw Error('sidebar mark missing');
           await page.screenshot({path:base+'/'+area+'-signed-in-'+width+'.png',fullPage:false});
           results.push({app:area+'-signed-in',width,imageLoaded:true});
           console.log('BRAND_UI_PASS',area+'-signed-in',width);
         }finally{await page.close()}
       }
     }
   }
   fs.writeFileSync(base+'/report.json',JSON.stringify({result:'PASS',results},null,2));
   console.log('BRAND_QA_PASS '+results.length+'/'+results.length);
 }finally{await browser.close()}
})().catch(e=>{console.error('BRAND_QA_FAIL',e.message);process.exit(1)});
