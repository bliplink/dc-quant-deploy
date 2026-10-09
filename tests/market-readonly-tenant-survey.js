'use strict';
// Public / read-only smoke survey. Never logs in or writes trade/tenant state.
const fs = require('fs');
const {chromium}=require('playwright');
const path=require('path');
const locations=(process.env.E2E_TENANTS||'DPGR6B,VPDHPM,BIHZYE,DUJE16,W8OSYE,ISMW9T,U6YQD4,T6X2PT,UJ2WZD,RCLRIO,QVPT5V,QS12O4')
 .split(',').map(x=>x.trim()).filter(Boolean);
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:18088';
const artifact=process.env.E2E_ARTIFACT_DIR||'/artifacts/market-readonly-survey';
const timeoutMs=Math.min(30000,Math.max(5000,Number(process.env.E2E_TENANT_TIMEOUT_MS||15000)));
const results=[];
(async()=>{
fs.mkdirSync(artifact,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 for(const location of locations){
  const page=await browser.newPage({viewport:{width:1366,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message.slice(0,160)));
  let detail={location,status:'FAIL',timestamp:new Date().toISOString()};
  try{
   const response=await page.goto(base+'/#/trade?location='+encodeURIComponent(location),{waitUntil:'domcontentloaded',timeout:timeoutMs});
   let initialQuoteTimeout=false;
   try {
     await page.waitForFunction(()=>document.querySelectorAll('.order-book-row--bid').length>=10 && document.querySelectorAll('.order-book-row--ask').length>=10,null,{timeout:timeoutMs});
   } catch (_) {
     initialQuoteTimeout=true;
     // Record a transient quote gap rather than silently converting it to PASS.
     // Give a bounded second window, then fail if the book is still absent.
     await page.waitForFunction(()=>document.querySelectorAll('.order-book-row--bid').length>=10 && document.querySelectorAll('.order-book-row--ask').length>=10,null,{timeout:timeoutMs});
   }
   const quote=await page.evaluate(()=>({
      bids:document.querySelectorAll('.order-book-row--bid').length,
      asks:document.querySelectorAll('.order-book-row--ask').length,
      lastPrice:document.querySelector('.bookMidPrice span')?.textContent?.trim()||'',
      klineStatus:window.__dcRealtimeKlineStatus||null,
      width:document.documentElement.scrollWidth
   }));
   await page.locator('.orderBookTabs button').last().click();
   await page.waitForFunction(()=>document.querySelectorAll('.recentTradeRow').length>0,null,{timeout:7000}).catch(()=>{});
   const trades=await page.evaluate(()=>({
     recentCount:document.querySelectorAll('.recentTradeRow').length,
     latest:(document.querySelector('.recentTradeRow')?.innerText||'').slice(0,75).trim()
   }));
   const issues=[];
   if(initialQuoteTimeout)issues.push('QUOTE_RECOVERED_AFTER_TIMEOUT');
   if(!quote.lastPrice || quote.lastPrice==='--')issues.push('LAST_PRICE_UNINITIALIZED');
   if(!quote.klineStatus)issues.push('KLINE_PUSH_NOT_YET_OBSERVED');
   if(!trades.recentCount)issues.push('NO_RECENT_TRADE_ROWS');
   if(errors.length)issues.push('JS_PAGE_ERROR');
   detail={location,status:errors.length?'FAIL':issues.length?'WARN':'PASS',http:response.status(),...quote,...trades,issues,errors};
  }catch(err){
   detail.error=String(err.message||err).slice(0,360);
   detail.errors=errors;
   await page.screenshot({path:path.join(artifact,'FAIL-'+location+'.png')}).catch(()=>{});
  }finally{await page.close()}
  results.push(detail);
  console.log('TENANT_SURVEY',detail.location,detail.status,'bid='+String(detail.bids||0),'ask='+String(detail.asks||0),'recent='+String(detail.recentCount||0),'issues='+JSON.stringify(detail.issues||[]));
 }
}finally{await browser.close()}
const report={createdAt:new Date().toISOString(),total:results.length,passed:results.filter(x=>x.status==='PASS').length,warned:results.filter(x=>x.status==='WARN').length,failed:results.filter(x=>x.status==='FAIL').length,results};
fs.writeFileSync(path.join(artifact,'survey-report.json'),JSON.stringify(report,null,2));
console.log('TENANT_SURVEY_COMPLETE',JSON.stringify({total:report.total,passed:report.passed,warned:report.warned,failed:report.failed,issues:results.filter(x=>x.issues?.length).map(x=>[x.location,x.issues])}));
if(report.failed)process.exit(1);
})().catch(err=>{console.error('TENANT_SURVEY_FATAL',err.stack||err);process.exit(2)});
