#!/usr/bin/env python3
"""Real public tenant registration -> TenantAdmin source/product creation.

This is opt-in on the local Demo ONLY. Passwords and session IDs live in memory
and must never be printed. Every mutation uses the public, authenticated API.
No direct DB writes or bypasses of the tenant security/session policy.
"""
import argparse
from decimal import Decimal
import os
from pathlib import Path
import re
import subprocess
import hashlib
import hmac
import json
import secrets
import time
import threading
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
    # T542: isolated fresh Demo runs in otc-t529-fresh-mysql, while the
    # one-click stack uses dc-saas-mysql. Never compare against the wrong DB.
    container = os.environ.get('OTC_E2E_MYSQL_CONTAINER', 'dc-saas-mysql')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', container):
        raise ValueError('Unsafe read-only MySQL container name')
    query=subprocess.run(['docker','exec',container,'sh','-c',
        'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N dc -e "$1"','--',statement],
        capture_output=True,text=True,timeout=15)
    if query.returncode:
        raise RuntimeError('Read-only MySQL verification unavailable')
    return [row.split('\t') for row in query.stdout.splitlines()]


def ha_marker(directory, marker, **fields):
    temporary=directory/(marker+'.tmp')
    temporary.write_text(json.dumps(fields,sort_keys=True)+'\n')
    temporary.replace(directory/(marker+'.json'))


def wait_ha_stage(directory, expected, timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status=json.loads((directory/'evidence.json').read_text())
        stage=status.get('stage')
        if stage==expected:
            if len(status.get(expected,{}))!=256:
                raise AssertionError('HA evidence does not contain all 256 partitions')
            return status
        if stage in ('failed','complete'):
            raise RuntimeError('HA exercise ended before '+expected)
        time.sleep(1)
    raise RuntimeError('HA exercise timed out waiting for '+expected)


def verify_ha_match(url, location, ids, phase):
    if not re.fullmatch('[A-Za-z0-9_-]+', location):
        raise AssertionError('Unsafe test tenant')
    orders=readonly_sql(
        "SELECT o.clord_id,o.user_id,e.exec_id FROM dc_orders o JOIN dc_orders_execorders e "
        "ON e.location=o.location AND e.user_id=o.user_id AND e.order_id=o.order_id AND e.last_qty>0 "
        "WHERE o.location='"+location+"' AND o.clord_id IN ('"+"','".join(ids)+"') "
        "AND o.security_id='BTC003USDT' ORDER BY o.clord_id")
    if (len(orders)!=2 or {row[0] for row in orders}!=set(ids)
            or len({row[1] for row in orders})!=2 or len({row[2] for row in orders})!=2):
        raise AssertionError('Expected exactly one distinct execution per authenticated order')
    postings_query=(
        "SELECT m.partition_id,m.source_epoch,m.journal_seq,m.event_id,"
        "JSON_UNQUOTE(JSON_EXTRACT(m.payload,'$.userID')),"
        "JSON_UNQUOTE(JSON_EXTRACT(m.payload,'$.sourceID')) "
        "FROM dc_trade_projection_mutation m "
        "WHERE m.location='"+location+"' AND m.entity_type='POSTING' "
        "AND m.source_type='TRADE_ATOMIC_MATCH_PAIR_PREPARED' "
        "AND JSON_UNQUOTE(JSON_EXTRACT(m.payload,'$.securityID'))='BTC003USDT' ORDER BY m.mutation_index")
    for attempt in range(25):
        postings=readonly_sql(postings_query)
        if len(postings)>=2:
            break
        time.sleep(2)
    if (len(postings)!=2 or len({tuple(row[:4]) for row in postings})!=1
            or {tuple(row[4:6]) for row in postings}!={tuple(row[1:3]) for row in orders}):
        raise AssertionError('Expected exactly one atomic Trade event with the two Order executions')
    partition,epoch,seq,event=postings[0][:4]
    if phase['service']=='TradeSvr' and [partition,int(epoch),int(seq)]!=phase['business_local_trade_coordinate']:
        raise AssertionError('Trade projection changed the original LOCAL settlement coordinate')
    return dict(orders=orders,postings=postings,partition=partition,source_epoch=int(epoch),
                journal_seq=int(seq),event_id=event,md_entry_id=verify_ha_market(url,location))


def verify_ha_market(url, location):
    for _ in range(25):
        market=ok(url,'MDSvr','queryPublicMarket',{'location':location,'securityID':'BTC003USDT'})
        entries=(market.get('recentTrades') or {}).get('NoMDEntries') or []
        exact=[row for row in entries if row.get('MDEntryID') and row.get('MDEntryTime')
               and Decimal(str(row.get('MDEntryPx','0')))==Decimal('90000')
               and Decimal(str(row.get('MDEntrySize','0')))==Decimal('0.001')]
        if exact:
            break
        time.sleep(1)
    if len(exact)!=1:
        raise AssertionError('Expected exactly one public MD print for the test match')
    return exact[0]['MDEntryID']


def verify_unfilled_immediate_orders(url, location, user, token, symbol, reference,
                                     mode, refresh_price, record):
    account_fields = ('Balance', 'UsedMargin', 'FreezedMargin', 'FreezedCommission')
    before = None
    if mode == 'TRADE':
        account = ok(url, 'TradeSvr', 'queryAccountBalance', {}, token, route_location=location)
        before = {field: Decimal(str(account[field])) for field in account_fields}
    cases = []
    for tif in ('IOC', 'FOK'):
        refresh_price()
        client = 'EMPTY-' + reference + '-' + tif
        ok(url, 'OrderSvr', 'placeOrder', {
            'OCType': 'OPEN', 'OrderQty': '0.001', 'OrdType': 'Limit',
            'ClOrdID': client, 'Terminal': 'API', 'AlgoName': 'cross',
            'Side': 'Buy', 'Price': '89900', 'UserID': user, 'MarketIndicator': '4',
            'TimeInForce': tif, 'SecurityID': symbol, 'ReduceOnly': 'false',
            'Demo': '0', 'Location': location,
        }, token)
        deadline = time.monotonic() + 60
        rows = []
        while time.monotonic() < deadline:
            rows = readonly_sql(
                "SELECT order_id,ord_status,cum_qty FROM dc_orders "
                f"WHERE location='{location}' AND user_id='{user}' "
                f"AND security_id='{symbol}' AND clord_id='{client}'")
            if len(rows) == 1 and rows[0][1] == 'Cancelled':
                break
            if len(rows) > 1 or rows and rows[0][1] in ('Filled', 'Partially_Filled', 'Rejected'):
                raise AssertionError('Unfilled immediate order has an unexpected terminal state')
            time.sleep(0.5)
        else:
            raise AssertionError('Unfilled immediate order did not durably cancel')
        order_id, state, cumulative = rows[0]
        if Decimal(cumulative) != 0:
            raise AssertionError('Unfilled immediate order gained executions')
        open_orders = ok(url, 'OrderSvr', 'queryOpenOrder', {
            'userid': user, 'securityid': symbol, 'location': location,
            'marketIndicator': '4', 'maxOrderCount': 100,
        }, token)
        if isinstance(open_orders, str):
            open_orders = json.loads(open_orders)
        if not isinstance(open_orders, list):
            raise AssertionError('Authenticated immediate-order readback is not a list')
        if any((row.get('ClOrdID') or row.get('ClOrderID') or row.get('clOrdID')) == client
               for row in open_orders):
            raise AssertionError('Cancelled immediate order remains open')
        trades = readonly_sql(
            "SELECT COUNT(*) FROM dc_orders_execorders "
            f"WHERE location='{location}' AND order_id='{order_id}' AND exec_type='Trade'")
        if trades != [['0']]:
            raise AssertionError('Unfilled immediate order produced a Trade execution')
        if mode == 'TRADE':
            account = ok(url, 'TradeSvr', 'queryAccountBalance', {}, token, route_location=location)
            after = {field: Decimal(str(account[field])) for field in account_fields}
            if after != before:
                raise AssertionError('Unfilled immediate cancellation changed or retained customer funds')
        cases.append({'time_in_force': tif, 'client_order_id': client, 'order_id': order_id,
                      'state': state, 'cumulative_quantity': cumulative})
    record('unfilled_immediate_orders_cancelled', mode=mode, cases=cases)


def accept_trade_scenario(url,location,suffix,broker_session,source_id,record,
                          near_simultaneous=False,sdk_signed=False,broker_client=None,
                          verify_private_streams=False,ha_evidence=None,ha_timeout=1900):
    """Small simulated, authenticated trader-to-trader match; no manual DB writes."""
    traders=[]
    active=[]
    trader_keys=[]
    private_feeds=[]
    private_threads=[]
    private_seen={}
    private_errors={}
    private_stop=threading.Event()
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
            trader={'role':role,'id':user_id,'session':token,'web_session':token}
            traders.append(trader)
            if sdk_signed:
                issued=ok(url,'LoginSvr','updateApiKey',{
                    'cid':'TRADER_KEY_'+suffix+'_'+role,
                    'label':'sdk-qa-'+suffix+'-'+role,'type':'trade'},token)
                if not issued.get('api_key') or not issued.get('secret_key'):
                    raise AssertionError('Trader API Key missing from self-service response')
                trader_keys.append((trader,issued['api_key']))
                from opentradingcore import OpenTradingCoreClient
                sdk=OpenTradingCoreClient.from_api_key(
                    base_url=url.rsplit('/httpapi/',1)[0],
                    api_key=issued['api_key'],api_secret=issued['secret_key'],
                    location=location)
                signed=sdk.login(mode='trader')
                if signed.client_type!='API' or signed.user_id!=str(user_id):
                    raise AssertionError('Signed Trader identity mismatch')
                trader['sdk']=sdk
                trader['session']=signed.token
                record('signed_trader_api_login',role=role)
                sdk.wait_for_product('BTC003USDT',timeout=12,poll_interval=1)
                sdk.set_leverage('BTC003USDT',10)
            else:
                ok(url,'TradeSvr','setLeverage',{'userID':user_id,'securityID':'BTC003USDT',
                    'location':location,'leverage':10},token)
            # A public Broker trading key is deliberately not allowed to
            # provision customer cash. Fund only through the tenant's normal
            # authenticated Demo account management flow.
            # The certified Common cash-in command requires an exact stable
            # idempotency key in Info1; never retry an ambiguous mutation.
            ok(url,'TradeSvr','cashIn',{'Amount':'1000','UserID':user_id,
                'Location':location,'Demo':'0',
                'Info1':'CUSTOM_CASH_'+suffix+'_'+role.upper()},token)
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
                if sdk_signed:
                    from opentradingcore import OpenTradingCoreError
                    try:
                        user['sdk'].place_limit_order('BTC003USDT',side.upper(),
                            '0.001',price,clord_id=client_id)
                        active.append((user,client_id))
                        return client_id
                    except OpenTradingCoreError as error:
                        if 'code=5004' in str(error):
                            if attempt==0:record('order_catalog_refresh_pending',role=user['role'])
                            time.sleep(5)
                            continue
                        raise
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
        if ha_evidence:
            fault=json.loads((ha_evidence/'evidence.json').read_text())
            commands=int(os.environ.get('MAC_DEMO_HA_TRADE_PREFIX_COMMANDS','0'))
            if commands and fault['service']=='TradeSvr':
                if not 4097<=commands<=8192:
                    raise ValueError('Use 4097 to 8192 real Trade setup commands for the large-prefix HA regression')
                for index in range(commands):
                    maker['sdk'].set_leverage('BTC003USDT',10+index%2)
                    if (index+1)%512==0:
                        record('ha_trade_large_prefix_preload_progress',commands=index+1)
                maker['sdk'].set_leverage('BTC003USDT',10)
                for _ in range(30):
                    heads=readonly_sql("SELECT partition_id,source_epoch,MAX(journal_seq) "
                        "FROM dc_trade_projection_mutation WHERE location='"+location+
                        "' GROUP BY partition_id,source_epoch")
                    if any(int(row[2])>=commands for row in heads):break
                    time.sleep(1)
                else:
                    raise AssertionError('Real Trade setup did not produce the required committed prefix')
                record('ha_trade_large_committed_prefix_before_fault',api_commands=commands,
                       committed_projection_heads=heads)
                refresh_price()
        if verify_private_streams:
            from websocket import WebSocketTimeoutException
            for trader in traders:
                role=trader['role']
                feed=trader['sdk']
                # Public surface has one client; the Demo's REST (33002) and
                # WS Upgrade (18088) share a hostname but use different ports.
                record('signed_private_stream_connect_attempt',role=role,gateway_port=18088)
                feed.connect_stream('private',gateway_base_url='http://127.0.0.1:18088')
                # A TOKEN resume rotates the HTTP session: immediately verify
                # that the same Python client can still make authenticated calls.
                assert feed.balances().get('Balance') is not None
                # The direct readback helpers below must use the new token too.
                # Otherwise the server correctly rejects the consumed SID.
                trader['session']=feed.session.token
                record('signed_private_stream_connected_and_http_session_rotated',role=role)
                feed.subscribe_balances()
                feed.subscribe_positions()
                feed.subscribe_order_status('BTC003USDT')
                feed.subscribe_executions('BTC003USDT')
                private_feeds.append(feed)
                private_seen[role]=[]
                private_errors[role]=[]
                def receive_notifications(stream=feed, user_role=role):
                    while not private_stop.is_set():
                        try:
                            for event in stream.events(channel='private'):
                                if private_stop.is_set():return
                                private_seen[user_role].append(str(event['topic']))
                        except WebSocketTimeoutException:
                            continue
                        except Exception as error:
                            if not private_stop.is_set():
                                private_errors[user_role].append(type(error).__name__)
                            return
                worker=threading.Thread(target=receive_notifications,daemon=True)
                worker.start()
                private_threads.append(worker)
            record('signed_private_streams_subscribed',accounts=2,topics_per_account=4)
        if near_simultaneous:
            # Launch both authenticated writes against the same new product
            # together. Do not wait for the Maker to become a resting New
            # order: this is exactly the previous concurrent bug scenario.
            from concurrent.futures import ThreadPoolExecutor
            from threading import Barrier
            gate=Barrier(2)
            def concurrent_put(user,side,name):
                gate.wait(timeout=8)
                started=time.monotonic_ns()
                client_id=put(user,side,name)
                return client_id,started
            with ThreadPoolExecutor(max_workers=2) as pool:
                sell=pool.submit(concurrent_put,maker,'Sell','MAKER')
                buy=pool.submit(concurrent_put,taker,'Buy','TAKER')
                resting,sell_at=sell.result(timeout=220)
                buying,buy_at=buy.result(timeout=220)
            record('near_simultaneous_orders_submitted',
                   request_launch_delta_ms=round(abs(sell_at-buy_at)/1e6,3),
                   sell=resting,buy=buying)
        else:
            resting=put(maker,'Sell','MAKER')
            record('maker_order_submitted',clientOrderId=resting)
            # In certified mode Common's committed OrderManager is the
            # admission authority. The MySQL dc_orders Projection may lag or
            # be unavailable, and MUST NOT block a real signed maker probe.
            # Do not weaken the independent *post-fill* Projection gate below.
            for wait in range(40):
                answer=call(url,'OrderSvr','queryOpenOrder',{
                    'location':location,'securityid':'BTC003USDT',
                    'marketIndicator':'4','userid':maker['id'],
                    'maxOrderCount':100},maker['session'])
                if answer.get('code')!=0:
                    raise RuntimeError('Authenticated Order maker readback rejected: '+
                                       str(answer.get('code'))+' '+str(answer.get('msg'))[:95])
                entries=answer.get('data')
                if not isinstance(entries,list):
                    raise AssertionError('Authenticated Order maker result is not a list')
                own=[]
                for entry in entries:
                    cid=entry.get('ClOrdID') or entry.get('ClOrderID') or entry.get('clOrdID')
                    if cid==resting:own.append(entry)
                if len(own)>1:raise AssertionError('Duplicate certified maker client ID')
                if own:
                    state=own[0].get('OrdStatus') or own[0].get('orderStatus')
                    if state=='New':
                        record('maker_resting_confirmed',source='authenticated_order_api')
                        time.sleep(1.5)
                        break
                    if state in ('Rejected','Canceled','Cancelled'):
                        raise AssertionError('Maker order left the resting state: '+str(state))
                time.sleep(1)
            else:
                raise AssertionError('Maker not found as New in authenticated Order state')
            def refresh_sessions():
                for trader in traders:
                    trader['session']=trader['sdk'].login(mode='trader').token

            def account_waterline():
                fields=('Balance','UsedMargin','FreezedMargin','FreezedCommission')
                result={}
                for trader in traders:
                    account=ok(url,'TradeSvr','queryAccountBalance',{},trader['session'],route_location=location)
                    if not account or any(account.get(field) is None for field in fields):
                        raise AssertionError('Signed Trade account read was unavailable')
                    result[trader['role']]={field:Decimal(str(account[field])) for field in fields}
                return result

            if ha_evidence:
                before=account_waterline()
                ha_marker(ha_evidence,'business-maker',location=location,client_order_id=resting)
                phase=wait_ha_stage(ha_evidence,'business_local_ready',ha_timeout)
                refresh_sessions()
                if phase['service']=='TradeSvr':
                    local=account_waterline()
                    if local!=before:
                        raise AssertionError('Witnessed LOCAL Trade account state differs from strict state')
                    refresh_price()
                    cancel_id=put(taker,'Buy','LOCAL-CANCEL','89999')
                    for _ in range(25):
                        orders=taker['sdk'].open_orders('BTC003USDT') or []
                        resting_cancel=[row for row in orders
                            if (row.get('ClOrdID') or row.get('ClOrderID'))==cancel_id
                            and (row.get('OrdStatus') or row.get('orderStatus'))=='New']
                        if len(resting_cancel)==1:
                            break
                        time.sleep(1)
                    else:
                        raise AssertionError('LOCAL Trade did not freeze margin for the cancellable order')
                    held_order=resting_cancel[0]
                    reservation=held_order.get('TradeReserveCommit','').split('/')
                    if (held_order.get('TradeReserveDurability')!='LOCAL_DURABLE_ASYNC'
                            or held_order.get('TradeReserveRpoRisk') is not True or len(reservation)!=3
                            or reservation[0] not in phase['survivor_local']
                            or int(reservation[1])!=phase['survivor_local'][reservation[0]]['epoch']
                            or int(reservation[2])<=0):
                        raise AssertionError('Client did not see the actual LOCAL Trade margin reservation and its risk')
                    held=account_waterline()
                    frozen_margin=held['taker']['FreezedMargin']-before['taker']['FreezedMargin']
                    frozen_commission=held['taker']['FreezedCommission']-before['taker']['FreezedCommission']
                    if held['maker']!=before['maker'] or frozen_margin<=0 or frozen_commission<0:
                        raise AssertionError('Trade did not apply the expected single-node account freeze')
                    record('ha_trade_local_margin_reserved',client_order_id=cancel_id,
                           reservation=reservation,frozen_margin=str(frozen_margin),
                           frozen_commission=str(frozen_commission))
                    order_id=held_order.get('OrderID') or held_order.get('orderID')
                    taker['sdk'].cancel_order('BTC003USDT',order_id,clord_id=cancel_id+'-REQUEST')
                    for _ in range(25):
                        cancel=readonly_sql("SELECT ord_status FROM dc_orders WHERE location='"+location+
                                            "' AND clord_id='"+cancel_id+"'")
                        if cancel in ([['Cancelled']],[['Canceled']]) and account_waterline()==before:
                            break
                        time.sleep(1)
                    else:
                        raise AssertionError('LOCAL Trade cancellation did not release the exact frozen margin')
                    record('ha_trade_local_cancel_released_margin',client_order_id=cancel_id)
                refresh_price()
            buying=put(taker,'Buy','TAKER')
            record('taker_order_submitted',clientOrderId=buying)
            if ha_evidence:
                local_accounts=0
                if phase['service']=='TradeSvr':
                    for _ in range(45):
                        local_accounts=0
                        for trader in traders:
                            position=ok(url,'TradeSvr','queryTradePosition',{'securityid':'BTC003USDT'},
                                        trader['session'],route_location=location)
                            side='Short' if trader['role']=='maker' else 'Long'
                            if position and Decimal(str(position.get(side+'Position','0')))==Decimal('0.001'):
                                local_accounts+=1
                        if local_accounts==2:
                            balances=account_waterline()
                            if any(Decimal(item['Balance'])>=Decimal(before[role]['Balance'])
                                   for role,item in balances.items()):
                                raise AssertionError('LOCAL Trade did not apply both financial after-states')
                            break
                        time.sleep(2)
                    else:
                        raise AssertionError('LOCAL Trade did not settle both positions while the peer was absent')
                    local_receipts={}
                    for _ in range(45):
                        for trader,client_id in ((maker,resting),(taker,buying)):
                            reports=ok(url,'OrderSvr','queryRuntimeExecOrder',{
                                'securityid':'BTC003USDT','maxOrderCount':100},
                                trader['session'],route_location=location)
                            exact=[row for row in reports or []
                                   if row.get('ClOrdID')==client_id and row.get('ExecType')=='Trade'
                                   and Decimal(str(row.get('LastQty','0')))==Decimal('0.001')]
                            if len(exact)>1:
                                raise AssertionError('Duplicate final LOCAL execution receipt')
                            if exact:
                                receipt=exact[0]
                                coordinate=receipt.get('TradeSettlementCommit','').split('/')
                                if (receipt.get('TradeSettlementDurability')!='LOCAL_DURABLE_ASYNC'
                                        or receipt.get('TradeSettlementQuorumDurable') is not False
                                        or receipt.get('TradeSettlementRpoRisk') is not True
                                        or len(coordinate)!=3 or coordinate[0] not in phase['survivor_local']
                                        or int(coordinate[1])!=phase['survivor_local'][coordinate[0]]['epoch']
                                        or int(coordinate[2])<=0):
                                    raise AssertionError('Final LOCAL receipt lost its actual durability or risk')
                                local_receipts[trader['role']]={key:receipt[key] for key in (
                                    'ExecID','TradeSettlementDurability','TradeSettlementQuorumDurable',
                                    'TradeSettlementRpoRisk','TradeSettlementCommit')}
                        if len(local_receipts)==2:
                            break
                        time.sleep(2)
                    else:
                        raise AssertionError('Final LOCAL executions waited for the absent Trade replica')
                    if local_receipts['maker']['TradeSettlementCommit']!=local_receipts['taker']['TradeSettlementCommit']:
                        raise AssertionError('Final LOCAL execution receipts disagree on the atomic Trade commit')
                    local_market=verify_ha_market(url,location)
                    if local_market not in {row['ExecID'] for row in local_receipts.values()}:
                        raise AssertionError('LOCAL public trade does not match either final execution')
                    record('ha_trade_local_final_receipts_before_replica_return',
                           receipts=local_receipts,public_trade_id=local_market)
                ha_marker(ha_evidence,'business-local',location=location,client_order_id=buying,
                          maker_client_order_id=resting,service=phase['service'],slot=phase['slot'],
                          verified_accounts=local_accounts,
                          final_local_receipts=local_receipts if phase['service']=='TradeSvr' else None)
                phase=wait_ha_stage(ha_evidence,'business_readback',ha_timeout)
                refresh_sessions()
                refresh_price()

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
        if verify_private_streams:
            # The server publishes the real market indicator (e.g. 0 or 1),
            # while the authenticated SDK subscription uses one wildcard
            # segment. Match the actual scoped topics, never assume "4".
            from opentradingcore.streams import MarketStreams
            targets={}
            for trader in traders:
                uid=str(trader['id'])
                role=trader['role']
                targets[role]=(
                    'dc.order.trade.BTC003USDT.*.'+uid+'.'+location,
                    'dc.order.status.BTC003USDT.'+uid+'.'+location,
                    'dc.trade.accountbalance.'+uid+'.'+location,
                    'dc.trade.position.'+uid+'.'+location,
                )
            def received_all(role):
                return all(any(MarketStreams._topic_matches(pattern,actual)
                               for actual in private_seen[role])
                           for pattern in targets[role])
            for attempt in range(15):
                if all(received_all(role) for role in targets) or any(private_errors.values()):break
                time.sleep(1)
            record('signed_private_stream_notifications',
                   per_role={role:sorted(set(private_seen[role])) for role in targets},
                   errors=private_errors)
            for role in targets:
                if not received_all(role):
                    raise AssertionError('Missing authenticated private streams: '+role)

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
            if sdk_signed:
                sdk=trader['sdk']
                assert sdk.balances().get('Balance') is not None
                assert sdk.positions('BTC003USDT').get(side+'Position') is not None
                assert sdk.order_history(symbol='BTC003USDT') is not None
                assert sdk.execution_history(symbol='BTC003USDT') is not None
                record('signed_trader_sdk_account_history',role=trader['role'])
        if ha_evidence:
            details=verify_ha_match(url,location,ids,phase)
            ha_marker(ha_evidence,'business-match',location=location,**details)
            record('ha_signed_match_exact_postings_and_market',source_epoch=details['source_epoch'],
                   journal_seq=details['journal_seq'],partition=details['partition'])
        else:
            verify_unfilled_immediate_orders(url, location, maker['id'], maker['session'],
                'BTC003USDT', suffix, 'TRADE', refresh_price, record)
        active.clear()
        return True
    finally:
        private_stop.set()
        for feed in private_feeds:
            feed.close_stream(channel='private')
        for worker in private_threads:
            worker.join(timeout=5)
        for trader,key in trader_keys:
            try:
                removed=call(url,'LoginSvr','deleteApiKey',{
                    'cid':'TRADER_KEY_DELETE_'+suffix,'api_key':key},trader['web_session'])
                record('trader_key_revoke',role=trader['role'],code=removed.get('code'))
            except Exception as error:
                record('trader_key_revoke_unconfirmed',role=trader['role'],reason=type(error).__name__)
        # Do not auto-close real positions upon failed acceptance. Cancel only
        # outstanding orders created by this run; never affect existing users.
        for trader in traders:
            try:
                ok(url,'OrderSvr','cancelAllOrder',{'UserID':trader['id'],
                    'SecurityID':'BTC003USDT','MarketIndicator':'4',
                    'AlgoName':'cross','Location':location},trader['session'])
            except Exception:
                pass


def run(url,with_traders=False,near_simultaneous=False,sdk_signed=False,verify_private_streams=False,
        ha_evidence=None,ha_timeout=1900):
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
            'permissions':'MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE',
            'cid':'BROKER_CREATE_'+suffix},token)
        if not broker.get('api_key') or not broker.get('secret_key'):
            raise AssertionError('Broker API key response lacked credentials')
        broker_key=broker['api_key']
        record('broker_key_issued')
        # Registry/policy propagation follows successful API key CREATE;
        # signed login is read-only and may safely retry only 7000/7004.
        for key_attempt in range(20):
            try:
                broker_login=signed_login(url,broker['api_key'],broker['secret_key'],location)
                break
            except RuntimeError as error:
                if not any(c in str(error) for c in ('code=7000','code=7004')) or key_attempt==19:
                    raise
                if key_attempt==0:record('signed_broker_key_registration_pending')
                time.sleep(3)
        record('signed_broker_key_ready',attempts=key_attempt+1)
        if broker_login.get('client_type')!='TenantAPI':
            raise AssertionError('Signed broker API identity was not TenantAPI')
        broker_session=broker_login['token']
        record('signed_tenant_broker_login')
        broker_sdk=None
        if sdk_signed:
            from opentradingcore import OpenTradingCoreClient
            broker_sdk=OpenTradingCoreClient.from_api_key(
                base_url=url.rsplit('/httpapi/',1)[0],api_key=broker['api_key'],
                api_secret=broker['secret_key'],location=location)
            assert broker_sdk.login(mode='broker').client_type=='TenantAPI'
            # Re-login can rotate/replace the API-key session. Never use the
            # previous manual signed_login token for subsequent broker writes.
            broker_session=broker_sdk.session.token
            record('python_broker_sdk_signed_login')
        # Publish only the currently bound source ID, not BTC003USDT itself.
        if sdk_signed:
            broker_sdk.publish_price(data_source_id=alt_id,index_price='90000',
                mark_price='90001',ttl_ms=60000,config_version=1,sequence=1,
                cid='PRICE_'+suffix)
            record('broker_price_publish_result',code=0,msg='SDK_ACCEPTED')
        else:
            quote=call(url,'APSSvr','publishBrokerPrice',{
                'location':location,'data_source_id':alt_id,
                'market_indicator':'4','index_price':'90000','mark_price':'90001',
                'source_time_ms':int(time.time()*1000),'ttl_ms':60000,
                'config_version':1,'sequence':1,'cid':'PRICE_'+suffix},broker_session)
            record('broker_price_publish_result',code=quote.get('code'),msg=quote.get('msg'))
            if quote.get('code')!=0:
                raise AssertionError('Broker price rejected by APS')
        if with_traders:
            accept_trade_scenario(url,location,suffix,broker_session,alt_id,record,
                                  near_simultaneous=near_simultaneous,
                                  sdk_signed=sdk_signed,broker_client=broker_sdk,
                                  verify_private_streams=verify_private_streams,
                                  ha_evidence=ha_evidence,ha_timeout=ha_timeout)
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
    parser.add_argument('--sdk-signed',action='store_true',
        help='Exercise self-issued Trader API Keys and signed Broker price; Demo funds are prepared by WEB sessions')
    parser.add_argument('--verify-private-streams',action='store_true',
        help='Require actual authenticated execution push to both Trader Python API sessions')
    parser.add_argument('--near-simultaneous',action='store_true',
        help='Submit opposing demo orders together; requires --execute --with-traders')
    parser.add_argument('--ha-evidence-dir',type=Path,help='Coordinate the signed match with a real Mac voter replacement')
    parser.add_argument('--ha-timeout',type=int,default=1900)
    args=parser.parse_args()
    if args.ha_evidence_dir and (
            not (args.execute and args.with_traders and args.sdk_signed)
            or args.near_simultaneous or args.verify_private_streams
            or not args.ha_evidence_dir.is_absolute() or not 60<=args.ha_timeout<=3900
            or not (args.ha_evidence_dir/'evidence.json').is_file()):
        parser.error('HA requires a sequential signed trader scenario and a live rollout evidence directory')
    if args.verify_private_streams and not (args.execute and args.with_traders and args.sdk_signed):
        parser.error('--verify-private-streams requires --execute --with-traders --sdk-signed')
    if args.sdk_signed and not (args.execute and args.with_traders):
        parser.error('--sdk-signed requires --execute --with-traders')
    if args.near_simultaneous and not (args.execute and args.with_traders):
        parser.error('--near-simultaneous requires --execute --with-traders')
    url=require_local(args.endpoint)
    if not args.execute:
        print('Refusing mutations without --execute')
        return 2
    if args.with_traders and not args.execute:
        parser.error('--with-traders requires --execute')
    return 0 if run(url,with_traders=args.with_traders,
                    near_simultaneous=args.near_simultaneous,
                    sdk_signed=args.sdk_signed,verify_private_streams=args.verify_private_streams,
                    ha_evidence=args.ha_evidence_dir,ha_timeout=args.ha_timeout) else 1

if __name__=='__main__':raise SystemExit(main())
