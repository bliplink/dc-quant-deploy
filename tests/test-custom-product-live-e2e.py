#!/usr/bin/env python3
"""Real public tenant registration -> TenantAdmin source/product creation.

This is opt-in on the local Demo ONLY. Passwords and session IDs live in memory
and must never be printed. Every mutation uses the public, authenticated API.
No direct DB writes or bypasses of the tenant security/session policy.
"""
import argparse
from decimal import Decimal
import subprocess
import hashlib
import hmac
import json
import secrets
import time
import urllib.request
from urllib.parse import urlparse


def require_local(url):
    parsed=urlparse(url)
    if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1'):
        raise ValueError('Demo acceptance must target localhost HTTP endpoint')
    return url.rstrip('/')+'/'


def call(url, service, method, content, session=None, timeout=28, route_location=None):
    headers={'Content-Type':'application/json'}
    if session:headers['sessionId']=session
    envelope={'serverName':service,'method':method,'content':content}
    location=content.get('Location') or content.get('location') or route_location
    if location:
        envelope['key']=str(location)
        if service=='OrderSvr':
            envelope['key']+='\x1f'+str(content.get('MarketIndicator','4'))+'\x1f'+str(content.get('SecurityID','BTC003USDT'))
    payload=json.dumps(envelope).encode()
    request=urllib.request.Request(url,payload,headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=timeout) as r:
        return json.load(r)


def signed_login(url,key,secret,location):
    body=json.dumps({'serverName':'LoginSvr','method':'apiKeyLogin','content':{
        'api_key':key,'location':location,'cid':'CUSTOM_PRODUCT_E2E_SIGNED'}},separators=(',',':')).encode()
    expiry=str(int(time.time()*1000)+60000)
    signature=hmac.new(secret.encode(),body+expiry.encode(),hashlib.sha256).hexdigest()
    api_url=url[:-len('/httpapi/')]+'/api'
    headers={'Content-Type':'application/json','cid':'CUSTOM_PRODUCT_E2E',
             'apikey':key,'expiry':expiry,'signature':signature}
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            urllib.request.Request(api_url,body,headers),timeout=30) as response:
        data=json.load(response)
    if data.get('code')!=0:
        raise RuntimeError(f'signed broker login rejected code={data.get("code")}, msg={data.get("msg")}')
    if not (data.get('data') or {}).get('token'):
        raise RuntimeError('signed broker login returned no token')
    return data['data']


def ok(url, service, method, content, session=None, route_location=None):
    result=call(url,service,method,content,session,route_location=route_location)
    if result.get('code')!=0:
        raise RuntimeError(f'{service}.{method} failed: code={result.get("code")}, msg={result.get("msg")}')
    return result.get('data')


def readonly_sql(statement):
    if not statement.lstrip().upper().startswith('SELECT ') or ';' in statement:
        raise ValueError('Only a single SELECT is allowed')
    query=subprocess.run(['docker','exec','dc-saas-mysql','sh','-c',
        'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc -e "$1"','--',statement],
        capture_output=True,text=True,timeout=15)
    if query.returncode:
        raise RuntimeError('Read-only MySQL verification unavailable')
    return [row.split('\t') for row in query.stdout.splitlines()]


def accept_trade_scenario(url,location,suffix,broker_session,source_id,record):
    """Small simulated, authenticated trader-to-trader match; no manual DB writes."""
    traders=[]
    active=[]
    try:
        for role in ('maker','taker'):
            username='custom_'+suffix.lower()+'_'+role
            password=secrets.token_urlsafe(24)
            registered=ok(url,'AdminSvr','tenantUserRegistration',{
                'action':'REGISTER','location':location,'username':username,
                'name':'Custom Product '+role,'email':username+'@acceptance.invalid',
                'password':password,'request_id':username,'cid':username})
            user_id=registered['user_id']
            identity=ok(url,'LoginSvr','SYS.ATS.LOGIN',{'method':'login',
                'cid':'LOGIN_'+username,'user_id':user_id,'user_name':username,
                'password':password,'client_type':'WEB','Location':location})
            token=identity['token']
            traders.append({'role':role,'id':user_id,'session':token})
            ok(url,'TradeSvr','setLeverage',{'userID':user_id,'securityID':'BTC003USDT',
                'location':location,'leverage':10},token)
            ok(url,'TradeSvr','cashIn',{'Amount':'1000','UserID':user_id,
                'Location':location,'Demo':'0'},token)
            # The successful cashIn response is durable business evidence;
            # its query endpoint sometimes reports a transient service route
            # registry gap. Retry reads only, never repeat the cash mutation.
            balance=None
            for probe in range(6):
                reply=call(url,'TradeSvr','queryAccountBalance',{},token,route_location=location)
                if reply.get('code')==0 and isinstance(reply.get('data'),dict):
                    balance=reply['data']
                    break
                if probe<5:time.sleep(2)
            if balance is None:
                record('balance_query_unavailable',role=role,
                       last_code=reply.get('code'))
                # The test should still probe private Order API acceptance;
                # the later projection/readback gate must establish funds.
                trader_balance=readonly_sql(
                    "SELECT balance FROM dc_users_balance WHERE location='"+location+
                    "' AND user_id='"+user_id+"' LIMIT 1")
                if len(trader_balance)!=1 or Decimal(trader_balance[0][0])<1000:
                    raise AssertionError('Neither session balance nor durable projection proves deposit')
                record('deposit_projected',role=role,balance=trader_balance[0][0])
            else:
                if Decimal(str(balance.get('Balance','0')))<Decimal('1000'):
                    raise AssertionError('Simulated trader deposit has not reached TradeSvr')
                record('trader_registered_funded',role=role,balance=str(balance['Balance']))

        # The AdminSvr catalog is authoritative. OrderSvr replicas receive
        # the product image asynchronously and can briefly reject a newly
        # created product as SYMBOL_NOTEXIST (code=5004). Only this definitive
        # pre-admission rejection may be re-attempted; no ambiguous mutations.
        price_seq=1
        price_at=0.0
        def refresh_price():
            nonlocal price_seq, price_at
            price_seq+=1
            fresh_time=int(time.time()*1000)
            quote=call(url,'APSSvr','publishBrokerPrice',{
                'location':location,'data_source_id':source_id,
                'market_indicator':'4','index_price':'90000','mark_price':'90001',
                'source_time_ms':fresh_time,'ttl_ms':60000,
                'config_version':1,'sequence':price_seq,
                'cid':'FRESH_PRICE_'+suffix+'_'+str(price_seq)},broker_session)
            if quote.get('code')!=0:
                raise RuntimeError('APS current-source refresh rejected: code='+str(quote.get('code')))
            price_at=time.monotonic()

        def put(user,side,reference,price='90000'):
            client_id='CUSTOM-'+suffix+'-'+reference
            content={'OCType':'OPEN','OrderQty':'0.001','OrdType':'Limit',
                'ClOrdID':client_id,'Terminal':'API','AlgoName':'cross',
                'Side':side,'Price':price,'UserID':user['id'],
                'MarketIndicator':'4','TimeInForce':'GTC',
                'SecurityID':'BTC003USDT','ReduceOnly':'false',
                'Demo':'0','Location':location}
            for attempt in range(48):
                if time.monotonic()-price_at>35:
                    refresh_price()
                reply=call(url,'OrderSvr','placeOrder',content,user['session'])
                if reply.get('code')==0:
                    active.append((user,client_id))
                    return client_id
                if reply.get('code')==5004 and reply.get('msg')=='SYMBOL_NOTEXIST':
                    if attempt==0:record('order_catalog_refresh_pending',role=user['role'])
                    time.sleep(5)
                    continue
                raise RuntimeError('OrderSvr.placeOrder rejected: code='+str(reply.get('code'))+
                                   ', msg='+str(reply.get('msg'))[:72])
            raise AssertionError('New product was not visible to OrderSvr within bounded refresh window')

        # TTL check is a true price event, not a simulation of published marks.
        refresh_price()
        for attempt in range(20):
            market=call(url,'MDSvr','queryPublicMarket',{'location':location,
                'securityID':'BTC003USDT'})
            mark=((market.get('data') or {}).get('ticker') or {}).get('MarkPrice')
            if market.get('code')==0 and mark=='90001':break
            time.sleep(1)
        else:
            raise AssertionError('Current source quote was not received by MD')
        record('current_source_mark_live',mark='90001')

        maker,taker=traders
        resting=put(maker,'Sell','MAKER')
        record('maker_order_submitted',clientOrderId=resting)
        # A successful placeOrder call only acknowledges submission. The
        # actual matching engine first completes asynchronous Trade Newing
        # admission; wait for the maker order to be resting before crossing.
        for wait in range(40):
            rows=readonly_sql(
                "SELECT ord_status FROM dc_orders WHERE location='"+location+
                "' AND clord_id='"+resting+"' LIMIT 1")
            if rows==[['New']]:
                time.sleep(1.5)
                break
            if rows and rows[0][0] in ('Rejected','Canceled','Cancelled'):
                raise AssertionError('Maker order left the resting state')
            time.sleep(1)
        else:
            raise AssertionError('Maker order never became a resting New order')
        record('maker_resting_confirmed')
        buying=put(taker,'Buy','TAKER')
        record('taker_order_submitted',clientOrderId=buying)

        # Actual executions must exist for each independently authenticated
        # trader; do not mistake HTTP order acknowledgement for a fill.
        from re import fullmatch
        ids=(resting,buying)
        if not all(fullmatch('[A-Za-z0-9_-]+',x) for x in ids):
            raise AssertionError('Unsafe client order ID')
        for attempt in range(30):
            query=("SELECT o.user_id,o.clord_id,o.ord_status,COUNT(e.exec_id) "
                "FROM dc_orders o LEFT JOIN dc_orders_execorders e "
                "ON e.location=o.location AND e.user_id=o.user_id "
                "AND e.order_id=o.order_id AND e.last_qty>0 "
                "WHERE o.location='"+location+"' AND o.security_id='BTC003USDT' "
                "AND o.clord_id IN ('"+ids[0]+"','"+ids[1]+"') "
                "GROUP BY o.user_id,o.clord_id,o.ord_status")
            rows=readonly_sql(query)
            if len(rows)==2 and all(row[2]=='Filled' and int(row[3])>=1 for row in rows):
                break
            time.sleep(1)
        else:
            record('match_projection_not_converged',orders=[r[1:4] for r in rows])
            raise AssertionError('Two real orders did not converge to Filled with executions')
        record('maker_taker_filled_and_projected',filled=2,executions=sum(int(r[3]) for r in rows))

        for trader in traders:
            position=ok(url,'TradeSvr','queryTradePosition',{'securityid':'BTC003USDT'},trader['session'],route_location=location)
            balance=ok(url,'TradeSvr','queryAccountBalance',{},trader['session'],route_location=location)
            side='Short' if trader['role']=='maker' else 'Long'
            if Decimal(str(position.get(side+'Position','0')))!=Decimal('0.001'):
                raise AssertionError(side+' position mismatch')
            if Decimal(str(balance.get('Balance','0')))<=0:
                raise AssertionError('Balance unavailable after fill')
            record('trader_posttrade_account',role=trader['role'],
                position=str(position[side+'Position']),balance=str(balance['Balance']))
        active.clear()
        return True
    finally:
        # Do not auto-close real positions upon failed acceptance. Cancel only
        # outstanding orders created by this run; never affect existing users.
        for trader in traders:
            try:
                ok(url,'OrderSvr','cancelAllOrder',{'UserID':trader['id'],
                    'SecurityID':'BTC003USDT','MarketIndicator':'4',
                    'AlgoName':'cross','Location':location},trader['session'])
            except Exception:
                pass


def run(url,with_traders=False):
    suffix=secrets.token_hex(5).upper()
    password=secrets.token_urlsafe(22)
    application_id='CUSTOM_PRODUCT_E2E_'+suffix
    email='custom-'+suffix.lower()+'@acceptance.invalid'
    checkpoints=[]
    broker_key=None
    admin_token=None
    def record(name, **details):
        checkpoints.append({'step':name,**details})
        print(json.dumps(checkpoints[-1],sort_keys=True),flush=True)
    try:
        application=ok(url,'ManagerSvr','tenantApplication',{
            'action':'SUBMIT','cid':application_id,'request_id':application_id,
            'organization_name':'OpenTradingCore Custom Product Acceptance '+suffix,
            'contact_name':'Acceptance','contact_email':email,'expected_users':12,
            'admin_password':password})
        if application.get('status')!='APPROVED':
            raise AssertionError('New test tenant not automatically approved')
        location=application['approved_location']
        record('tenant_approved',location=location)
        login=ok(url,'LoginSvr','SYS.ATS.LOGIN',{'method':'login',
            'cid':'LOGIN_'+suffix,'user_id':'tenantadmin','user_name':'tenantadmin',
            'password':password,'client_type':'TenantAdmin','Location':location})
        if not login.get('token'):raise AssertionError('No TenantAdmin session token')
        token=login['token'];admin_token=token
        record('tenant_admin_authenticated')
        source_id='QA_CUSTOM_'+suffix
        alt_id='QA_ALT_'+suffix
        primary=ok(url,'AdminSvr','tenantDataSourceAdmin',{
            'action':'CREATE','location':location,'cid':'SOURCE_'+suffix,
            'data_source_id':source_id,'source_name':'Custom price '+suffix,
            'source_type':'CUSTOM','source_symbol':'BTCUSD_CUSTOM'},token)
        record('custom_source_created',source=source_id,refresh=primary.get('query_symbol_refresh'))
        product=ok(url,'AdminSvr','tenantProductDataSource',{
            'action':'CREATE','location':location,'cid':'PRODUCT_'+suffix,
            'security_id':'BTC003USDT','product_name':'BTC QA Custom 003',
            'data_source_id':source_id,'template_security_id':'BTCUSDT'},token)
        if not product or not product.get('enabled'):raise AssertionError('Product not enabled on CREATE')
        record('product_created',product='BTC003USDT',refresh=product.get('query_symbol_refresh'))
        # Public Trading Web list must include the new product and only own tenant.
        for attempt in range(15):
            visible=ok(url,'AdminSvr','querySymbol',{'location':location})
            symbols=[s.get('symbol') for s in (visible or {}).get('symbols',[])]
            if 'BTC003USDT' in symbols:break
            time.sleep(1)
        if 'BTC003USDT' not in symbols:raise AssertionError('new product absent from public querySymbol')
        record('anonymous_product_visible',count=len(symbols))
        public=ok(url,'AdminSvr','querySymbol',{'location':'H2FIJU'})
        if any(s.get('symbol')=='BTC003USDT' for s in public.get('symbols',[])):
            raise AssertionError('Product leaked to another tenant')
        record('tenant_isolation_verified')
        # A different source code can replace the sole current product binding.
        alt=ok(url,'AdminSvr','tenantDataSourceAdmin',{
            'action':'CREATE','location':location,'cid':'SOURCE_ALT_'+suffix,
            'data_source_id':alt_id,'source_name':'Alternate manual source '+suffix,
            'source_type':'CUSTOM','source_symbol':'BTCUSD_ALTERNATE'},token)
        record('alternate_source_created',source=alt_id)
        rebound=ok(url,'AdminSvr','tenantProductDataSource',{
            'action':'BIND','location':location,'cid':'BIND_'+suffix,
            'security_id':'BTC003USDT','data_source_id':alt_id},token)
        if rebound.get('data_source_id')!=alt_id:
            raise AssertionError('BIND result does not reflect the selected source')
        record('single_current_source_rebound',selected=alt_id,refresh=rebound.get('query_symbol_refresh'))
        listing=ok(url,'AdminSvr','tenantProductDataSource',{
            'action':'LIST','location':location},token)
        rows=[x for x in listing if x.get('security_id')=='BTC003USDT']
        if len(rows)!=1 or rows[0].get('data_source_id')!=alt_id:
            record('product_admin_list_mismatch',
                   rowCount=len(rows),
                   rowSources=[r.get('data_source_id') for r in rows],
                   rowKeys=[list(r.keys()) for r in rows])
            raise AssertionError('Current bound source list differs from BIND result')
        record('one_current_binding_persisted')
        broker=ok(url,'LoginSvr','tenantApiKeyAdmin',{
            'action':'CREATE','type':'broker','label':'custom-product-e2e-'+suffix,
            'cid':'BROKER_CREATE_'+suffix},token)
        if not broker.get('api_key') or not broker.get('secret_key'):
            raise AssertionError('Broker API key response lacked credentials')
        broker_key=broker['api_key']
        record('broker_key_issued')
        broker_login=signed_login(url,broker['api_key'],broker['secret_key'],location)
        if broker_login.get('client_type')!='TenantAPI':
            raise AssertionError('Signed broker API identity was not TenantAPI')
        broker_session=broker_login['token']
        record('signed_tenant_broker_login')
        # Publish only the currently bound source ID, not BTC003USDT itself.
        quote=call(url,'APSSvr','publishBrokerPrice',{
            'location':location,'data_source_id':alt_id,
            'market_indicator':'4','index_price':'90000','mark_price':'90001',
            'source_time_ms':int(time.time()*1000),'ttl_ms':60000,
            'config_version':1,'sequence':1,'cid':'PRICE_'+suffix},broker_session)
        record('broker_price_publish_result',code=quote.get('code'),msg=quote.get('msg'))
        if quote.get('code')!=0:
            raise AssertionError('Broker price rejected by APS')
        if with_traders:
            accept_trade_scenario(url,location,suffix,broker_session,alt_id,record)
        return True
    except Exception as e:
        record('FAILED',error=type(e).__name__,message=str(e)[:220])
        return False
    finally:
        # Never leave a newly created, privileged Broker API key active after
        # a completed or failed QA execution. No plaintext key is logged.
        if broker_key and admin_token:
            try:
                removed=call(url,'LoginSvr','tenantApiKeyAdmin',{
                    'action':'DELETE','api_key':broker_key,
                    'cid':'QA_BROKER_CLEANUP_'+suffix},admin_token)
                record('broker_key_cleanup',deleted=removed.get('code')==0)
            except Exception as error:
                record('broker_key_cleanup_failed',reason=type(error).__name__)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint',default='http://127.0.0.1:33002/httpapi/')
    parser.add_argument('--execute',action='store_true',help='Create fresh test tenant and products')
    parser.add_argument('--with-traders',action='store_true',
        help='Simulated account deposits and two-trader limit-order matching')
    args=parser.parse_args()
    url=require_local(args.endpoint)
    if not args.execute:
        print('Refusing mutations without --execute')
        return 2
    if args.with_traders and not args.execute:
        parser.error('--with-traders requires --execute')
    return 0 if run(url,with_traders=args.with_traders) else 1

if __name__=='__main__':raise SystemExit(main())
