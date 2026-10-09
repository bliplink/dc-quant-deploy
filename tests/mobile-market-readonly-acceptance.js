// Real Chromium read-only spot checks of maker quotes and Tape-driven trades.
const {chromium}=require('playwright');
const fs=require('fs');
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:18088';
const loc=process.env.E2E_LOCATION||'DPGR6B';
const dir='/artifacts/acceptance-followup-20261009';
const summary=[];
(async()=>{
  fs.mkdirSync(dir,{recursive:true});
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  try{
    for(const width of [390,768,1366]){
      const page=await browser.newPage({viewport:{width,height:844}});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      try{
        const response=await page.goto(base+'/#/trade?location='+encodeURIComponent(loc),{waitUntil:'domcontentloaded',timeout:26000});
        // On phones the chart is the default workspace; test 5M there first.
        // The order book mounts only after switching to Order/交易.
        let initialMobile5m=null;
        if(await page.locator('.mobileWorkspaceTabs').count()) {
          await page.waitForFunction(()=>[...document.querySelectorAll('.mobileChartIntervals button')].some(x=>x.textContent.trim().toLowerCase()==='5m'&&x.className.includes('active')),null,{timeout:16000});
          initialMobile5m=true;
          await page.locator('.mobileWorkspaceTabs button').nth(1).click();
          await page.locator('.mobileOrderBook').waitFor({state:'visible',timeout:15000});
        }
        await page.locator('.orderBookTabs button[aria-selected="true"]').first().waitFor({timeout:27000});
        await page.waitForFunction(()=>document.querySelectorAll('.orderBookWrap .order-book-row--ask').length>0&&document.querySelectorAll('.orderBookWrap .order-book-row--bid').length>0,null,{timeout:45000});
        const book=await page.evaluate(()=>({
          asks:document.querySelectorAll('.orderBookWrap .order-book-row--ask').length,
          bids:document.querySelectorAll('.orderBookWrap .order-book-row--bid').length,
          price:document.querySelector('.orderBookWrap .bookMidPrice span')?.textContent?.trim(),
          pageWidth:document.documentElement.scrollWidth,viewport:window.innerWidth,
          logo:!!document.querySelector('.head-user img.brandMark'),
          rowFont:getComputedStyle(document.querySelector('.orderBookWrap .order-book-row--ask')||document.body).fontSize
        }));
        await page.screenshot({path:dir+'/mobile-market-book-'+width+'.png',fullPage:false});
        const tab=page.locator('.orderBookTabs button').last();
        await tab.click();
        await page.waitForFunction(()=>document.querySelectorAll('.recentTradeRow').length>0,null,{timeout:28000});
        const trades=await page.evaluate(()=>({
          recentRows:document.querySelectorAll('.recentTradeRow').length,
          first:(document.querySelector('.recentTradeRow')?.textContent||'').trim().slice(0,95),
          recentFont:getComputedStyle(document.querySelector('.recentTradeRow')||document.body).fontSize,
          active:[...document.querySelectorAll('.orderBookTabs button')].filter(x=>x.getAttribute('aria-selected')==='true').map(x=>x.textContent.trim())
        }));
        await page.screenshot({path:dir+'/mobile-market-trades-'+width+'.png',fullPage:false});
        if(errors.length||book.asks<1||book.bids<1||trades.recentRows<1||!book.logo||book.pageWidth>width+1)throw Error('bad market state '+JSON.stringify({errors,book,trades}));
        if(width<=479&&(parseFloat(book.rowFont)<10||parseFloat(trades.recentFont)<10))
          throw Error('mobile market rows remain smaller than 10px '+JSON.stringify({bookFont:book.rowFont,tradeFont:trades.recentFont}));
        summary.push({width,http:response.status(),initialMobile5m,...book,...trades,errorCount:errors.length});
        console.log('MOBILE_MARKET_PASS',width,'bids='+book.bids,'asks='+book.asks,'trades='+trades.recentRows,'last='+book.price,'initial5m='+initialMobile5m,'font='+book.rowFont,'doc='+book.pageWidth);
      }finally{await page.close()}
    }
  }finally{await browser.close()}
  fs.writeFileSync(dir+'/mobile-market-report.json',JSON.stringify({result:'PASS',location:loc,summary},null,2));
  console.log('MOBILE_MARKET_ACCEPTANCE_PASS '+summary.length+'/3');
})().catch(e=>{console.error('MOBILE_MARKET_ACCEPTANCE_FAIL',e.message);process.exit(1)});
