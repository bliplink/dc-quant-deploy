'use strict';
const fs = require('fs');
const {chromium}=require('playwright');
const ids=(process.env.E2E_TENANTS||'DPGR6B,QS12O4,BIHZYE,UJ2WZD,T6X2PT').split(',').filter(Boolean);
const base=process.env.E2E_BASE_URL||'http://127.0.0.1:18088';
const out=process.env.E2E_ARTIFACT_DIR||'/artifacts/first-paint';
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const b=await chromium.launch({headless:true,args:['--no-sandbox']});
  const results=[];
  for(const id of ids){
    const p=await b.newPage({viewport:{width:1366,height:900}});
    const errors=[];p.on('pageerror',e=>errors.push(e.message.slice(0,140)));
    const t=Date.now();
    const marks={tenant:id,errors};
    try{
      await p.goto(base+'/#/trade?location='+encodeURIComponent(id),{waitUntil:'domcontentloaded',timeout:20000});
      marks.domContentMs=Date.now()-t;
      for(let step=0;step<75;step++){
        const st=await p.evaluate(()=>{
          const kl=window.__dcKlineStatus||null;
          const bookBids=document.querySelectorAll('.order-book-row--bid').length;
          const bookAsks=document.querySelectorAll('.order-book-row--ask').length;
          return {chartBars:kl?.bars||0,chartHistoryRows:kl?.receivedRows||0,
            iframe:!!document.querySelector('.TVChartContainer iframe'),
            bookBids,bookAsks,price:(document.querySelector('.bookMidPrice span')?.textContent||'').trim(),
            statusReady:document.querySelector('[data-market-ready]')?.getAttribute('data-market-ready')||null,
            statusChart:document.querySelector('[data-market-chart]')?.getAttribute('data-market-chart')||null,
            statusBook:document.querySelector('[data-market-book]')?.getAttribute('data-market-book')||null,
            symbol:document.querySelector('.symbolMarket')?.innerText?.slice(0,32)};
        });
        const elapsed=Date.now()-t;
        if(st.iframe&&!('chartFrameMs' in marks))marks.chartFrameMs=elapsed;
        if(st.chartBars>0&&!('chartBarsMs' in marks))marks.chartBarsMs=elapsed;
        if(st.bookBids>=10&&st.bookAsks>=10&&!('bookFullMs' in marks))marks.bookFullMs=elapsed;
        if(st.price&&st.price!=='--'&&!('priceMs' in marks))marks.priceMs=elapsed;
        if(st.statusReady==='true'&&!('marketReadyMs' in marks))marks.marketReadyMs=elapsed;
        marks.last=st;
        if('chartBarsMs'in marks&&'bookFullMs'in marks&&'priceMs'in marks&&
          (st.statusReady===null || st.statusReady==='true'))break;
        await p.waitForTimeout(250);
      }
      console.log('FIRST_PAINT_TIMING',JSON.stringify(marks));
    }catch(e){marks.error=String(e.message||e).slice(0,260);console.log('FIRST_PAINT_ERROR',JSON.stringify(marks))}
    results.push(marks);await p.close();
  }
  await b.close();
  fs.writeFileSync(out+'/first-paint.json',JSON.stringify(results,null,2));
  console.log('FIRST_PAINT_DONE',JSON.stringify({samples:results.length,chartMs:results.map(x=>x.chartBarsMs||null),bookMs:results.map(x=>x.bookFullMs||null),startupReadyMs:results.map(x=>x.marketReadyMs||null)}));
})().catch(e=>{console.error(e.stack);process.exit(2)});
