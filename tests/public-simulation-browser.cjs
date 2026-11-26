const fs=require('fs'), crypto=require('crypto'), zlib=require('zlib');
const {chromium}=require(process.env.PLAYWRIGHT_ROOT || 'playwright');
const dir=process.env.AUDIT_DIR;
if(!dir || !fs.statSync(dir).isDirectory())throw Error('Set AUDIT_DIR to a private, existing evidence directory');
const origin=process.env.SIMULATION_ORIGIN || 'https://trade.opentradingcore.com', location=process.env.DEMO_LOCATION||'';
if(!/^[A-Z0-9]{6}$/.test(location))throw new Error('Expected an explicit Demo tenant');
function acknowledged(reply){return reply.code!=null && Number(reply.code)===0;}
function decoded(payload){
 try{
  const bytes=Buffer.isBuffer(payload)?payload:Buffer.from(payload);
  if(bytes.length<22||bytes.readInt16BE(4)!==22)return;
  const a=bytes.readInt16BE(14),b=bytes.readInt16BE(16),c=bytes.readInt16BE(18),d=bytes.readInt16BE(20);
  if(Math.min(a,b,c,d)<0)return;
  const base=22+a,method=bytes.subarray(base+b,base+b+c).toString('utf8');
  if(!/^(cashIn|cashOut|placeOrder|cancelOrder|queryOpenOrder|previewOrder)$/i.test(method))return;
  let body=bytes.subarray(base+b+c+d,bytes.readInt32BE(0));
  if(body[0]===0x1f&&body[1]===0x8b)body=zlib.gunzipSync(body);
  let data=JSON.parse(body.toString('utf8'));
  if(typeof data.content==='string')data={...data,...JSON.parse(data.content)};
  if(data.content&&typeof data.content==='object')data={...data,...data.content};
  return {method,clientOrderId:data.ClOrdID,
   fundingRequest:/^WEB-CASH-(?:IN|OUT)-[a-f0-9]{32}$/.test(data.Info1)?data.Info1:undefined,
   code:data.code??data.Code??null,
   message: String(data.msg??data.message??'').replace(/[a-z0-9_-]{28,}/g,'[redacted]').slice(0,200)};
 }catch{}
}

async function newPage(browser,label){
 const ctx=await browser.newContext({locale:'en-US',viewport:{width:1440,height:930}});
 await ctx.addInitScript(()=>localStorage.setItem('dc-trade-language','en'));
 const page=await ctx.newPage(), frames=[];
 const notices=new Set();
 await page.exposeFunction('auditNotice',value=>notices.add(value));
 await page.addInitScript(()=>new MutationObserver(()=>{const txt=document.querySelector('.ant-message-notice-content')?.innerText;if(txt)window.auditNotice(txt.slice(0,160));}).observe(document,{childList:true,subtree:true}));
 const username='qaBZ'+label+Date.now().toString(36)+crypto.randomBytes(2).toString('hex');
 const password='Qa-'+crypto.randomBytes(15).toString('base64url')+'7!';
 page.on('websocket',ws=>{
  for(const [event,direction] of [['framesent','sent'],['framereceived','received']]){
   ws.on(event,e=>{const x=decoded(e.payload);if(x)frames.push({...x,at:Date.now(),direction});});
  }
 });
 await page.goto(origin+'/#/register?location='+location,{waitUntil:'domcontentloaded',timeout:35000});
 const form=page.locator('.tenant-grid input');
 await form.first().waitFor({timeout:16000});
 for(const [i,value] of [username,'Demo matched-order audit',username+'@acceptance.invalid',password,password].entries())
  await form.nth(i).fill(value);
 await page.getByRole('button',{name:'Create account',exact:true}).click();
 await page.waitForURL('**/#/trade?location='+location,{timeout:35000,waitUntil:'commit'}).catch(()=>{throw Error('Registration or automatic sign-in failed for '+label+' on '+new URL(page.url()).hash.split('?')[0]+': '+[...notices].slice(-2).join(' / '));});
 await page.waitForFunction((tenant)=>{const x=JSON.parse(sessionStorage.getItem('loginData')||'{}');return x.user_id&&x.location===tenant},location,{timeout:20000});
 const picker=page.locator('.symbolDiv').first();
 await picker.waitFor({timeout:18000});
 if(!(await picker.innerText()).includes('BTCUSDT')){
  await picker.click();
  await page.locator('.drawDiv').filter({hasText:/BTCUSDT/}).first().click({timeout:12000});
 }
 await picker.filter({hasText:/BTCUSDT/}).waitFor({timeout:12000});
 const session={page,frames,username};
 session.deposit=await funding(session,'cashIn','100');
 return session;
}
async function orderReply(session,start,method='placeOrder'){
 const {page,frames}=session;
 const until=Date.now()+20000;
 while(Date.now()<until){
  const sent=frames.slice(start).find(x=>x.direction==='sent'&&x.method===method);
  const receive=frames.slice(start).find(x=>x.direction==='received'&&x.method===method&&x.code!==null);
  if(sent && receive && receive.at>=sent.at)return {code:receive.code,clientOrderId:sent?.clientOrderId,fundingRequest:sent?.fundingRequest,error:receive.message,durationMs:sent?receive.at-sent.at:null,toast:(await page.locator('.ant-message-notice-content').allTextContents()).slice(-4)};
  await page.waitForTimeout(125);
 }
 return {timedOut:true,preview:frames.slice(start).filter(x=>x.method==='previewOrder'&&x.code!==null).slice(-4),toast:(await page.locator('.ant-message-notice-content').allTextContents()).slice(-4)};
}
async function funding(session,method,amount,reuse){
 const {page,frames}=session;
 const start=frames.length,withdraw=method==='cashOut';
 const title=withdraw?'Withdraw':'Deposit';
 if(reuse){
  await page.evaluate(({key,tenant,amount})=>{
   const user=JSON.parse(sessionStorage.getItem('loginData')).user_id;
   sessionStorage.setItem(JSON.stringify(['demo-cash-out',tenant,user,Number(amount).toFixed(8)]),key);
  },{key:reuse,tenant:location,amount});
 }
 await page.locator('.accountInfoWrap').getByText(title,{exact:true}).click();
 const modal=page.locator('.ant-modal:visible').filter({hasText:title});
 if(/wallet address|network address|on.chain|提币地址|链上转账/i.test(await modal.innerText()))
  throw Error('Unexpected real transfer fields');
 await modal.locator('input').fill(amount);
 await modal.getByRole('button',{name:'Confirm '+title}).click();
 const reply=await orderReply(session,start,method);
 if(reply.code==null||Number(reply.code)!==0||!reply.fundingRequest||(reuse&&reply.fundingRequest!==reuse))
  throw Error('Simulated funding did not return the expected acknowledgment');
 await modal.waitFor({state:'hidden',timeout:15000});
 return {...reply,amount};
}
async function place(session,side,price,kind="Limit",options={}){
 const {page,frames}=session;
 const start=frames.length,panel=page.locator('.placeOrderWrap');
 await panel.getByRole('button',{name:kind,exact:true}).click();
 if(kind==='Limit') await panel.getByRole('textbox',{name:'Limit Price',exact:true}).fill(price);
 if(options.reduceOnly!==undefined){
  await panel.getByRole('checkbox',{name:'Reduce Only',exact:true}).setChecked(options.reduceOnly);
 }
 if(options.postOnly)await panel.getByRole('checkbox',{name:'Post Only',exact:true}).check();
 await panel.getByRole('textbox',{name:'Amount',exact:true}).fill('0.001');
 const action=options.reduceOnly?(side==='buy'?/Close Short/i:/Close Long/i)
  :(side==='buy'?/Open Long|Buy\s*\/\s*Long/i:/Open Short|Sell\s*\/\s*Short/i);
 await panel.getByRole('button',{name:action}).click();
 return orderReply(session,start);
}
async function observeTrade(session,expectedCount=1){
 const {page}=session;
 await page.locator('.orderWrap').getByText('Trade History',{exact:true}).click({force:true});
 const row=page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr').filter({hasText:'BTCUSDT'}).nth(expectedCount-1);
 if(!await row.waitFor({timeout:45000}).then(()=>true,()=>false)){
   const refresh=page.locator('.orderWrap .ant-tabs-tabpane-active').getByRole('button',{name:'Refresh',exact:true});
   await refresh.click();
   const afterRefresh=await row.waitFor({timeout:15000}).then(()=>true,()=>false);
   return {visible:false,visibleAfterManualRefresh:afterRefresh};
 }
 return {visible:true,btcQuantityVisible:/0\.001/.test(await row.innerText())};
}
async function cleanResting(session){
 const {page}=session;
 await page.locator('.orderWrap').getByText('Open Orders',{exact:true}).click({force:true});
 const rows=page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr').filter({hasText:'BTCUSDT'});
 const row=rows.first();
 if(!await row.isVisible())return {restingOrder:false};
 const c=row.getByText('Cancel',{exact:true});
 if(!await c.count())return {restingOrder:true,cancelControl:false};
 await c.click();
 return {restingOrder:true,canceled:await row.waitFor({state:'hidden',timeout:12000}).then(()=>true,()=>false)};
}
async function dormantOrder(session,type,markPrice,callbackMode){
 const {page,frames}=session;
 const panel=page.locator('.placeOrderWrap');
 const start=frames.length;
 await panel.getByRole('button',{name:'Conditional',exact:true}).click();
 await panel.getByLabel('Conditional Type',{exact:true}).selectOption(type);
 await panel.getByRole('checkbox',{name:'Reduce Only',exact:true}).setChecked(false);
 await panel.getByLabel('Trigger By',{exact:true}).selectOption('Mark Price');
 const trailing=type==='TrailingStopMarket';
 const threshold=type.startsWith('Stop') ? Math.ceil(markPrice*1.15) : Math.floor(markPrice*.85);
 await panel.getByLabel(trailing?'Activation Price (optional)':'Trigger Price',{exact:true}).fill(String(threshold));
 if(!type.endsWith('Market'))await panel.getByLabel('Limit Price',{exact:true}).fill(String(Math.round(markPrice)));
 if(trailing){
  await panel.getByLabel('Callback Type',{exact:true}).selectOption(callbackMode);
  await panel.getByLabel('Callback',{exact:true}).fill(callbackMode==='Percent'?'1.5':'100');
 }
 await panel.getByLabel('Amount',{exact:true}).fill('0.001');
 await panel.getByRole('button',{name:/Open Long|Buy\s*\/\s*Long/i}).click();
 const received=await orderReply(session,start);
 if(received.code==null||Number(received.code)!==0)throw Error(`Conditional ${type} rejected: ${JSON.stringify(received)}`);
 await page.locator('.orderWrap').getByText('Open Orders',{exact:true}).click({force:true});
 const row=page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
  .filter({hasText:'BTCUSDT'}).filter({hasText:'Untriggered'});
 await row.first().waitFor({timeout:12000});
 if(await row.count()!==1)throw Error(`Conditional ${type} did not produce exactly one waiting order`);
 const canceled=await cleanResting(session);
 if(!canceled.canceled)throw Error(`Conditional ${type} did not cancel`);
 return {type,callbackMode,received,canceled:true};
}
async function triggeredClose(session,markPrice){
 const {page,frames}=session;
 const panel=page.locator('.placeOrderWrap');
 const start=frames.length;
 await panel.getByRole('button',{name:'Conditional',exact:true}).click();
 await panel.getByLabel('Conditional Type',{exact:true}).selectOption('TriggerMarket');
 await panel.getByRole('checkbox',{name:'Reduce Only',exact:true}).check();
 await panel.getByLabel('Trigger By',{exact:true}).selectOption('Mark Price');
 // The next authentic Mark Price tick should cross this buy threshold.
 await panel.getByLabel('Trigger Price',{exact:true}).fill(String(Math.ceil(markPrice*1.15)));
 await panel.getByLabel('Amount',{exact:true}).fill('0.001');
 await panel.getByRole('button',{name:/Close Short/i}).click();
 const received=await orderReply(session,start);
 if(Number(received.code)!==0||!received.clientOrderId)throw Error('Conditional reduce-only close was denied');
 return received;
}
module.exports={newPage,place,observeTrade,acknowledged};
if(require.main===module)(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const result={location,contract:'BTCUSDT',quantity:'0.001',login:'dedicated simulated accounts'};
 let buyer,seller;
 try{
  buyer=await newPage(browser,'buy');
  seller=await newPage(browser,'sell');
  result.accounts=[buyer.username,seller.username];
  result.deposits=[buyer.deposit,seller.deposit];
  // Funding and waiting-order cases are independent of two-sided market fills.
  result.withdrawal=await funding(seller,'cashOut','1');
  result.withdrawalReplay=await funding(seller,'cashOut','1',result.withdrawal.fundingRequest);
  await buyer.page.waitForFunction(()=>/\d/.test(document.querySelector('.marketMetricMark span:last-child')?.textContent||''),null,{timeout:20000});
  const market=await buyer.page.evaluate(()=>{
   const values=(selector)=>Array.from(document.querySelectorAll(selector),
      node=>Number(node.textContent.replace(/,/g,''))).filter(x=>Number.isFinite(x)&&x>0);
   const bid=values('.order-book-row--bid .bid-price');
   const ask=values('.order-book-row--ask .ask-price');
   const markText=document.querySelector('.marketMetricMark span:last-child').textContent;
   return {bestBid:bid.length?Math.max(...bid):null,bestAsk:ask.length?Math.min(...ask):null,
    markPrice:Number(markText.replace(/,/g,''))};
  });
  result.publicBook=market;
  if(!Number.isFinite(market.markPrice)||market.markPrice<=0)throw Error('An authoritative mark price is required');
   result.conditions=[];
   for(const type of ['TriggerLimit','TriggerMarket','Stop','StopMarket','TakeProfit','TakeProfitMarket']){
    result.conditions.push(await dormantOrder(buyer,type,market.markPrice));
   }
   for(const mode of ['Percent','Distance'])
    result.conditions.push(await dormantOrder(buyer,'TrailingStopMarket',market.markPrice,mode));

  const base=market.bestBid??(market.bestAsk===null?market.markPrice:market.bestAsk-1);
  result.price=String(Math.max(1,Math.ceil(base+1)<(market.bestAsk??Infinity)
    ? Math.ceil(base+1):Math.floor(base)));
  result.buyLimit=await place(buyer,'buy',result.price,'Limit',{postOnly:true});
  if(!acknowledged(result.buyLimit))throw Error('Controlled maker bid was denied');
  await buyer.page.locator('.orderWrap').getByText('Open Orders',{exact:true}).click({force:true});
  await buyer.page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
    .filter({hasText:'BTCUSDT'}).first().waitFor({timeout:12000});
  result.makerWasResting=true;
  result.sellMarket=await place(seller,'sell',null,'Market');
  if(acknowledged(result.sellMarket)) {
   [result.buyerExecution,result.sellerExecution]=await Promise.all([observeTrade(buyer),observeTrade(seller)]);
   await buyer.page.screenshot({path:dir+'/simulated-market-fill-buyer.png'});
   await seller.page.screenshot({path:dir+'/simulated-market-fill-seller.png'});
   if(!result.buyerExecution.visible||!result.sellerExecution.visible)throw Error('Both sides of the opening execution are required');
   const closingPrice=await seller.page.locator('.order-book-row--ask .ask-price').allTextContents();
   const prices=closingPrice.map(value=>Number(value.replace(/,/g,''))).filter(value=>Number.isFinite(value)&&value>0);
   result.closePrice=String(prices.length?Math.min(...prices):Number(result.price));
   result.closeLongLimit=await place(buyer,'sell',result.closePrice,'Limit',{reduceOnly:true,postOnly:true});
   if(!acknowledged(result.closeLongLimit))throw Error('Reduce-only maker ask was denied');
   await buyer.page.locator('.orderWrap').getByText('Open Orders',{exact:true}).click({force:true});
   await buyer.page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
    .filter({hasText:'BTCUSDT'}).first().waitFor({timeout:12000});
   result.closeShortMarket=await place(seller,'buy',null,'Market',{reduceOnly:true});
   if(!acknowledged(result.closeShortMarket))throw Error('Reduce-only market buy was denied');
   [result.longClosedExecution,result.shortClosedExecution]=await Promise.all([observeTrade(buyer,2),observeTrade(seller,2)]);
   if(!result.longClosedExecution.visible||!result.shortClosedExecution.visible)
    throw Error('Both sides of the reduce-only execution are required');
   result.triggerOpeningMaker=await place(buyer,'buy',result.price,'Limit',{reduceOnly:false,postOnly:true});
   if(!acknowledged(result.triggerOpeningMaker))throw Error('Second controlled maker bid was denied');
   await buyer.page.locator('.orderWrap').getByText('Open Orders',{exact:true}).click({force:true});
   await buyer.page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
    .filter({hasText:'BTCUSDT'}).first().waitFor({timeout:12000});
   result.triggerOpeningTaker=await place(seller,'sell',null,'Market',{reduceOnly:false});
   if(!acknowledged(result.triggerOpeningTaker))throw Error('Second controlled market short was denied');
   [result.triggerOpeningBuyerExecution,result.triggerOpeningSellerExecution]
    =await Promise.all([observeTrade(buyer,3),observeTrade(seller,3)]);
   if(!result.triggerOpeningBuyerExecution.visible||!result.triggerOpeningSellerExecution.visible)
    throw Error('Both positions must open before the conditional close');
   result.triggerClosingMaker=await place(buyer,'sell',result.closePrice,'Limit',{reduceOnly:true,postOnly:true});
   if(!acknowledged(result.triggerClosingMaker))throw Error('Controlled conditional-close maker ask was denied');
   await buyer.page.locator('.orderWrap').getByText('Open Orders',{exact:true}).click({force:true});
   await buyer.page.locator('.orderWrap .ant-tabs-tabpane-active .ant-table-tbody tr')
    .filter({hasText:'BTCUSDT'}).first().waitFor({timeout:12000});
   result.triggerClosingParent=await triggeredClose(seller,market.markPrice);
   [result.triggerClosingBuyerExecution,result.triggerClosingSellerExecution]
    =await Promise.all([observeTrade(buyer,4),observeTrade(seller,4)]);
   if(!result.triggerClosingBuyerExecution.visible||!result.triggerClosingSellerExecution.visible)
    throw Error('Both executions must publish after the authentic mark triggers the conditional close');
  }
 }catch(e){result.error=e.message.slice(0,265);}
 finally{
  if(buyer)result.buyerCleanup=await cleanResting(buyer).catch(e=>({error:e.message.slice(0,130)}));
  if(seller)result.sellerCleanup=await cleanResting(seller).catch(e=>({error:e.message.slice(0,130)}));
  fs.writeFileSync(dir+'/matched-market-acceptance.json',JSON.stringify(result,null,2));
  await browser.close();
 }
 console.log(JSON.stringify({...result,accounts:undefined}));
 if(result.error||!result.shortClosedExecution?.visible||result.conditions?.length!==8
    ||!result.triggerClosingSellerExecution?.visible||!result.withdrawalReplay?.fundingRequest)process.exitCode=1;
})().catch(e=>{console.error(e.message);process.exit(1)});
