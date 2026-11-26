// One new customer crosses funded Robot quotes, then closes both positions.
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const {chromium} = require(process.env.PLAYWRIGHT_ROOT || 'playwright');
const {newPage, place, observeTrade, acknowledged} = require('./public-simulation-browser.cjs');
const tenant = process.env.DEMO_LOCATION;
const directory = process.env.AUDIT_DIR;
const origin = new URL(process.env.SIMULATION_ORIGIN || 'https://trade.opentradingcore.com');
const generation = process.env.SIMULATION_GENERATION;
if (!/^mac-demo-[0-9]{8}-[0-9]{6}$/.test(generation || '')) throw Error('Specify the active Mac demo generation');
const project = execFileSync('docker',['inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}','dc-saas-mysql'],{encoding:'utf8'}).trim();
if (project !== generation || !['trade.opentradingcore.com','localhost','127.0.0.1'].includes(origin.hostname))
  throw Error('Check the simulation host and deployment');
function select(query) {
  return execFileSync('docker',['exec','-i','dc-saas-mysql','sh','-c',
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -BN dc'],
    {input:query,encoding:'utf8',timeout:12000}).trim();
}
const maker = select(`SELECT j.maker_user_id FROM dc_tenant_liquidity_bootstrap j
 JOIN dc_tenant_robot r ON r.location=j.location AND r.api_user_id=j.maker_user_id
 WHERE j.location='${tenant}' AND j.status='COMPLETE' AND j.step='DONE'
 AND j.funding_request_id=CONCAT('PUBLIC_SIM_MAKER_',LOWER(j.application_id)) AND j.funding_confirmed=1
 AND r.security_id='BTCUSDT' AND r.enabled=1 AND r.runtime_status='RUNNING' AND r.hedge_enabled=0
 AND r.open_order_count>=2 AND r.last_heartbeat_time>=NOW()-INTERVAL 30 SECOND
 AND JSON_EXTRACT(r.strategy_config,'$.public_simulation_maker')=true`);
if (!/^\d{1,32}$/.test(maker)) throw Error('No active, funded customer-facing maker for this tenant');
const pause = ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function waitForProof(query) {
  const end=Date.now()+45000;
  do {
    const rows=select(query);
    if (rows) return rows;
    await pause(500);
  } while(Date.now()<end);
  throw Error('Settlement or projection proof did not arrive within 45 seconds');
}
async function pairProof(customer,clientOrderId,side,reduce) {
  if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(clientOrderId || '')) throw Error('Missing customer order reference');
  const base="CONCAT_WS(CHAR(31),m.location,m.security_id,m.order_id,t.order_id,'0',";
  // Use the same two deterministic execution IDs as OrderCertifiedMatchSettlementEnvelope.
  const rows=await waitForProof(`SELECT t.exec_id,m.exec_id,t.last_qty,t.last_px,t.fee,t.realized_Pnl
    FROM dc_orders o JOIN dc_orders_execorders t ON t.location=o.location AND t.user_id=o.user_id AND t.order_id=o.order_id
    JOIN dc_orders_execorders m ON m.location=t.location AND m.security_id=t.security_id AND m.market_indicator=t.market_indicator
        AND m.last_qty=t.last_qty AND m.last_px=t.last_px AND m.side<>t.side
        AND m.exec_type='Trade' AND m.maker=1 AND m.user_id='${maker}'
    WHERE o.location='${tenant}' AND o.user_id='${customer}' AND o.clord_id='${clientOrderId}'
        AND o.reduce_only=${reduce?1:0} AND o.ord_status='Filled' AND o.cum_qty=0.001 AND o.security_id='BTCUSDT'
        AND t.exec_type='Trade' AND t.side='${side}' AND t.maker=0
        AND t.exec_id=CONCAT('E',LEFT(SHA2(${base}'taker'),256),30))
        AND m.exec_id=CONCAT('E',LEFT(SHA2(${base}'maker'),256),30))`);
  const legs=rows.split('\n').map(row=>row.split('\t'));
  if (legs.some(row=>row.slice(2).some(value=>!Number.isFinite(Number(value)))) ||
      Math.abs(legs.reduce((sum,row)=>sum+Number(row[2]),0)-0.001)>1e-12)
    throw Error('Executed quantity, price, fee or realized P&L did not reconcile');
  return legs;
}
(async()=>{
  const result={tenant,maker,legs:[]};
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  try {
    const session=await newPage(browser,'single');
    const user=await session.page.evaluate(()=>JSON.parse(sessionStorage.getItem('loginData')).user_id);
    if (!/^\d{1,32}$/.test(user) || user===maker) throw Error('Customer and maker identities must be independent');
    result.customer=user;
    for (const [side,reduce] of [['buy',false],['sell',true],['sell',false],['buy',true]]) {
      const quote = side==='buy'?'.order-book-row--ask .ask-price':'.order-book-row--bid .bid-price';
      await session.page.locator(quote).first().waitFor({timeout:15000});
      const displayed=await session.page.locator(quote).allTextContents();
      const prices=displayed.map(x=>Number(x.replace(/,/g,''))).filter(x=>Number.isFinite(x)&&x>0);
      if (!prices.length) throw Error('No executable prices displayed');
      const reply=await place(session,side,null,'Market',{reduceOnly:reduce});
      if (!acknowledged(reply)) throw Error('Market order was rejected or timed out');
      const legs=await pairProof(user,reply.clientOrderId,side==='buy'?'Buy':'Sell',reduce);
      const visible=await observeTrade(session,result.legs.flatMap(x=>x.executions).length+legs.length);
      result.legs.push({side,reduce,displayedBest:side==='buy'?Math.min(...prices):Math.max(...prices),
        clientOrderId:reply.clientOrderId,executions:legs,historyVisible:visible.visible});
      if (!visible.visible) throw Error('Trade history did not update automatically');
    }
    result.closingBalance=await waitForProof(`SELECT b.balance FROM dc_users_balance b JOIN dc_orders_position p
      ON p.location=b.location AND p.user_id=b.user_id
      WHERE b.location='${tenant}' AND b.user_id='${user}' AND p.security_id='BTCUSDT'
      AND p.long_position=0 AND p.short_position=0 AND b.used_margin=0 AND b.freezed_margin=0 AND b.freezed_commission=0
      AND b.balance=100+(SELECT SUM(e.fee+e.realized_Pnl) FROM dc_orders_execorders e
          WHERE e.location=b.location AND e.user_id=b.user_id AND e.exec_type='Trade')`);
    await session.page.screenshot({path:directory+'/funded-maker-settled.png'});
  } catch(error) {
    result.error=error.message;
    process.exitCode=1;
  } finally {
    fs.writeFileSync(directory+'/funded-maker-acceptance.json',JSON.stringify(result,null,2),{mode:0o600});
    await browser.close();
    console.log(JSON.stringify({tenant,settledOrders:result.legs.length,closingBalance:result.closingBalance,error:result.error}));
  }
})().catch(e=>{console.error(e.message);process.exitCode=1});
