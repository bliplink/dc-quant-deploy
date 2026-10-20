#!/usr/bin/env python3
"""Demo-only, opt-in real Order-only product acceptance; isolated QA tenant.

No TradeSvr deposits, leverage, balance or position mutation; no HA injection.
Requires --execute; cleans up the temporary signed Broker price API Key.
Never automatically retries ambiguous orders or creates non-Demo customers.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import time
import sys
import threading

HELPERS = Path(__file__).with_name('test-custom-product-live-e2e.py')
spec = importlib.util.spec_from_file_location('otc_custom_e2e_helpers', str(HELPERS))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

def sql(statement):
    return h.readonly_sql(statement)

def run(endpoint,verify_streams=False):
    suffix=secrets.token_hex(5).upper()
    password=secrets.token_urlsafe(23)
    location=None
    admin_session=None
    broker_api_key=None
    maker=taker=None
    market_stream=None
    stream_thread=None
    stream_stop=threading.Event()
    stream_topics=[]
    stream_errors=[]
    def checkpoint(name,**details):
        print(json.dumps({'checkpoint':name,**details},sort_keys=True),flush=True)
    try:
        application=h.ok(endpoint,'ManagerSvr','tenantApplication',{
            'action':'SUBMIT','cid':'ORDER_ONLY_'+suffix,'request_id':'ORDER_ONLY_'+suffix,
            'organization_name':'Order-only acceptance '+suffix,
            'contact_name':'QA','contact_email':'orderonly-'+suffix.lower()+'@acceptance.invalid',
            'expected_users':12,'admin_password':password})
        if application.get('status')!='APPROVED':
            raise AssertionError('Tenant auto approval failed')
        location=application['approved_location']
        checkpoint('tenant_created',location=location)
        login=h.ok(endpoint,'LoginSvr','SYS.ATS.LOGIN',{'method':'login',
            'cid':'LOGIN_ADMIN_'+suffix,'user_id':'tenantadmin','user_name':'tenantadmin',
            'password':password,'client_type':'TenantAdmin','Location':location})
        admin_session=login['token']
        source='QA_OO_'+suffix
        h.ok(endpoint,'AdminSvr','tenantDataSourceAdmin',{
            'action':'CREATE','location':location,'cid':'SOURCE_OO_'+suffix,
            'data_source_id':source,'source_name':'Order only quote '+suffix,
            'source_type':'CUSTOM','source_symbol':'BTCUSD_ORDERONLY'},admin_session)
        product=h.ok(endpoint,'AdminSvr','tenantProductDataSource',{
            'action':'CREATE','location':location,'cid':'PRODUCT_OO_'+suffix,
            'security_id':'BTC003USDT','product_name':'Order-only BTC 003',
            'data_source_id':source,'template_security_id':'BTCUSDT',
            'matching_mode':'ORDER_ONLY'},admin_session)
        assert product['matching_mode']=='ORDER_ONLY' and product['enabled']
        rows=h.ok(endpoint,'AdminSvr','tenantProductDataSource',{
            'action':'LIST','location':location},admin_session)
        assert next(p['matching_mode'] for p in rows if p['security_id']=='BTC003USDT')=='ORDER_ONLY'
        db_mode=sql("SELECT matching_mode FROM dc_tenant_symbol WHERE location='"+location+"' AND security_id='BTC003USDT'")
        assert db_mode==[['ORDER_ONLY']],db_mode
        checkpoint('product_created_in_order_only_mode',product='BTC003USDT')

        def create_trader(label):
            username='oo_'+suffix.lower()+'_'+label
            userpass=secrets.token_urlsafe(24)
            data=h.ok(endpoint,'AdminSvr','tenantUserRegistration',{
                'action':'REGISTER','location':location,'username':username,
                'name':'Order-only '+label,'email':username+'@acceptance.invalid',
                'password':userpass,'request_id':username,'cid':username})
            uid=str(data['user_id'])
            assert uid.isdigit() and len(uid)==12, 'new user_id is not the 12-digit tenant allocator format'
            logged=h.ok(endpoint,'LoginSvr','SYS.ATS.LOGIN',{'method':'login',
                'cid':'LOGIN_'+username,'user_id':uid,'user_name':username,
                'password':userpass,'client_type':'WEB','Location':location})
            return {'user_id':uid,'token':logged['token']}
        maker=create_trader('maker');taker=create_trader('taker')
        checkpoint('trader_ids_are_numeric',both_12_digit=True)
        # Non-funded users are supposed to trade an Order-only product.
        # Auto-approved tenants bootstrap liquidity users asynchronously.
        # Their demo cash-ins are unrelated to this product's Order-only
        # settlement; assert strictly against the TWO unfunded QA traders.
        trader_scope=(" WHERE location='"+location+"' AND user_id IN ('"+
                      maker['user_id']+"','"+taker['user_id']+"')")
        balance_query=("SELECT user_id,COALESCE(balance,0) FROM dc_users_balance"+
                       trader_scope+" ORDER BY user_id")
        position_query=("SELECT user_id,security_id,long_position,short_position "
                        "FROM dc_orders_position"+trader_scope+
                        " AND security_id='BTC003USDT' ORDER BY user_id")
        before=sql(balance_query)
        before_positions=sql(position_query)
        checkpoint('trade_balances_before',trader_rows=len(before),
                   position_rows=len(before_positions))

        broker=h.ok(endpoint,'LoginSvr','tenantApiKeyAdmin',{
            'action':'CREATE','type':'broker','label':'order-only-qa-'+suffix,
            'permissions':'MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE',
            'cid':'BROKER_OO_'+suffix},admin_session)
        broker_api_key=broker['api_key']
        # Signed API key registration may lag CREATE. Retrying LOGIN is safe;
        # never replay orders or other ambiguous writes.
        for login_attempt in range(30):
            try:
                broker_session=h.signed_login(
                    endpoint,broker['api_key'],broker['secret_key'],location)['token']
                break
            except RuntimeError as error:
                if (not any(code in str(error) for code in ('code=7000', 'code=7004'))
                        or login_attempt == 29):
                    raise
                if login_attempt == 0:
                    checkpoint('broker_registration_pending')
                time.sleep(3)
        checkpoint('broker_authenticated',attempts=login_attempt+1)
        price_sequence=0
        def publish_price():
            nonlocal price_sequence
            price_sequence+=1
            h.ok(endpoint,'APSSvr','publishBrokerPrice',{
                'location':location,'data_source_id':source,'market_indicator':'4',
                'index_price':'90000','mark_price':'90001',
                'source_time_ms':int(time.time()*1000),'ttl_ms':60000,
                'config_version':1,'sequence':price_sequence,
                'cid':'PRICE_OO_'+suffix+'_'+str(price_sequence)},broker_session)
        publish_price()
        for i in range(25):
            market=h.call(endpoint,'MDSvr','queryPublicMarket',{'location':location,
                'securityID':'BTC003USDT'})
            if market.get('code')==0 and ((market.get('data') or {}).get('ticker') or {}).get('MarkPrice')=='90001':
                break
            time.sleep(1)
        else:raise AssertionError('MD custom mark price not visible')
        checkpoint('mark_price_live')
        if verify_streams:
            # Attach the *actual* public Python SDK before the trade, rather
            # than interpreting a subscription ACK as proof of notifications.
            from opentradingcore import MarketStreams
            from websocket import WebSocketTimeoutException
            market_stream=MarketStreams(base_url='http://127.0.0.1:18088',
                                        location=location)
            market_stream.connect()
            market_stream.subscribe_ticker('BTC003USDT')
            market_stream.subscribe_recent_trades('BTC003USDT')
            market_stream.subscribe_order_book('BTC003USDT')
            market_stream.subscribe_candles('BTC003USDT',interval='5m')
            def observe_market():
                while not stream_stop.is_set():
                    try:
                        for event in market_stream.events():
                            if stream_stop.is_set():return
                            stream_topics.append(str(event.get('topic')))
                    except WebSocketTimeoutException:
                        continue
                    except Exception as error:
                        if not stream_stop.is_set():
                            stream_errors.append(type(error).__name__)
                        return
            stream_thread=threading.Thread(target=observe_market,daemon=True)
            stream_thread.start()
            checkpoint('python_public_stream_subscribed',topics=5)
        orders=[]
        def place(trader,side,name):
            client_id='OO-'+suffix+'-'+name
            request={'OCType':'OPEN','OrderQty':'0.001','OrdType':'Limit',
                'ClOrdID':client_id,'Terminal':'API','AlgoName':'cross',
                'Side':side,'Price':'90000','UserID':trader['user_id'],
                'MarketIndicator':'4','TimeInForce':'GTC',
                'SecurityID':'BTC003USDT','ReduceOnly':'false','Demo':'0','Location':location}
            for attempt in range(30):
                # Retry only definitive 5004 rejection BEFORE admission.
                result=h.call(endpoint,'OrderSvr','placeOrder',request,trader['token'])
                if result.get('code')==0:
                    orders.append(client_id)
                    return client_id
                if result.get('code')==5004 and 'SYMBOL_NOTEXIST' in str(result.get('msg')):
                    if attempt%5==4:publish_price()
                    time.sleep(3)
                    continue
                raise AssertionError('Order-only write rejected: '+str(result.get('code'))+' '+str(result.get('msg'))[:90])
            raise AssertionError('Order-only catalog was not ready within 90s')
        maker_id=place(maker,'Sell','MAKER')
        checkpoint('maker_submitted',order=maker_id)
        for i in range(35):
            states=sql("SELECT ord_status FROM dc_orders WHERE location='"+location+"' AND clord_id='"+maker_id+"' LIMIT 1")
            if states==[['New']]:break
            if states and states[0][0] in ('Rejected','Canceled','Cancelled'):
                raise AssertionError('Maker rejected after admission: '+str(states))
            time.sleep(1)
        else:raise AssertionError('Order-only maker not resting')
        taker_id=place(taker,'Buy','TAKER')
        checkpoint('taker_submitted',order=taker_id)
        for i in range(45):
            states=sql("SELECT clord_id,ord_status,cum_qty FROM dc_orders WHERE location='"+location+"' AND clord_id IN ('"+maker_id+"','"+taker_id+"') ORDER BY clord_id")
            if len(states)==2 and all(row[1]=='Filled' for row in states):break
            time.sleep(2)
        else:raise AssertionError('Order-only orders did not both fill: '+str(states))
        fills=sql("SELECT exec_id,order_id,side,last_qty,last_px FROM dc_orders_execorders WHERE location='"+location+"' AND security_id='BTC003USDT' AND last_qty>0")
        if len(fills)!=2 or len({row[0] for row in fills})!=2:
            raise AssertionError('Missing/duplicate order-only execution reports: '+str(len(fills)))
        after=sql(balance_query)
        after_positions=sql(position_query)
        if before!=after:
            raise AssertionError("ORDER_ONLY changed one of its traders' TradeSvr balances")
        if before_positions!=after_positions:
            raise AssertionError("ORDER_ONLY changed one of its traders' TradeSvr positions")
        checkpoint('order_only_filled_no_trade_balance_mutation',orders=2,
                   executions=len(fills),trader_balance_rows=len(after),
                   trader_position_rows=len(after_positions))
        if verify_streams:
            # Market notifications are async; wait a short bounded window
            # after the durable fill and demand the actual recent-trades push.
            expected='dc.md.market.trade.BTC003USDT.'+location
            for _ in range(10):
                if expected in stream_topics or stream_errors:break
                time.sleep(1)
            checkpoint('python_public_stream_observed',received=len(stream_topics),
                       topic_counts={topic:stream_topics.count(topic)
                                     for topic in sorted(set(stream_topics))},
                       errors=stream_errors)
            if expected not in stream_topics:
                raise AssertionError('Python SDK received no actual recent-trades push after two Filled orders')
        return 0
    except Exception as error:
        checkpoint('FAILED',error_type=type(error).__name__,message=str(error)[:210])
        return 1
    finally:
        stream_stop.set()
        if market_stream is not None:market_stream.close()
        if stream_thread is not None:stream_thread.join(timeout=5)
        if broker_api_key and admin_session:
            try:
                result=h.call(endpoint,'LoginSvr','tenantApiKeyAdmin',{
                    'action':'DELETE','api_key':broker_api_key,
                    'cid':'CLEANUP_ORDER_ONLY_'+suffix},admin_session)
                checkpoint('broker_key_revoked',code=result.get('code'))
            except Exception as error:
                checkpoint('broker_key_revocation_failed',error_type=type(error).__name__)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Required for Demo tenant creation and test orders')
    parser.add_argument('--endpoint',default='http://127.0.0.1:33002/httpapi/')
    parser.add_argument('--verify-streams',action='store_true',
                        help='Additionally require an actual Python SDK recent-trades notification')
    args=parser.parse_args()
    if not args.execute: parser.error('refusing mutations without --execute')
    sys.exit(run(h.require_local(args.endpoint),verify_streams=args.verify_streams))
