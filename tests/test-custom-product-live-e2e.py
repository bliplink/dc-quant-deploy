#!/usr/bin/env python3
"""Real public tenant registration -> TenantAdmin source/product creation.

This is opt-in on the local Demo ONLY. Passwords and session IDs live in memory
and must never be printed. Every mutation uses the public, authenticated API.
No direct DB writes or bypasses of the tenant security/session policy.
"""
import argparse
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


def call(url, service, method, content, session=None, timeout=28):
    headers={'Content-Type':'application/json'}
    if session:headers['sessionId']=session
    payload=json.dumps({'serverName':service,'method':method,'content':content}).encode()
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


def ok(url, service, method, content, session=None):
    result=call(url,service,method,content,session)
    if result.get('code')!=0:
        raise RuntimeError(f'{service}.{method} failed: code={result.get("code")}, msg={result.get("msg")}')
    return result.get('data')


def run(url):
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
    args=parser.parse_args()
    url=require_local(args.endpoint)
    if not args.execute:
        print('Refusing mutations without --execute')
        return 2
    return 0 if run(url) else 1

if __name__=='__main__':raise SystemExit(main())
