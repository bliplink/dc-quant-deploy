#!/usr/bin/env python3
"""Real local Demo-only old-source revocation -> new price -> TTL-expiry E2E.

Creates one fresh tenant and product, no trader accounts, cash or orders.
Broker API Key is revoked on any exit; no direct database mutations.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import time

HELPERS = Path(__file__).with_name('test-custom-product-live-e2e.py')
spec = importlib.util.spec_from_file_location('otc_custom_test_helpers', str(HELPERS))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def run(endpoint):
    suffix=secrets.token_hex(5).upper()
    location=None
    admin_token=None
    broker_key=None
    def checkpoint(name, **kw):
        print(json.dumps({'checkpoint':name,**kw},sort_keys=True),flush=True)
    try:
        password=secrets.token_urlsafe(24)
        registered=h.ok(endpoint,'ManagerSvr','tenantApplication',{
            'action':'SUBMIT','cid':'SOURCE_TTL_'+suffix,
            'request_id':'SOURCE_TTL_'+suffix,
            'organization_name':'Source TTL QA '+suffix,
            'contact_name':'QA','contact_email':'source-'+suffix.lower()+'@acceptance.invalid',
            'expected_users':8,'admin_password':password})
        if registered.get('status')!='APPROVED':
            raise AssertionError('New QA tenant not automatically approved')
        location=registered['approved_location']
        login=h.ok(endpoint,'LoginSvr','SYS.ATS.LOGIN',{
            'method':'login','cid':'SOURCE_ADMIN_'+suffix,
            'user_id':'tenantadmin','user_name':'tenantadmin',
            'password':password,'client_type':'TenantAdmin','Location':location})
        admin_token=login['token']
        checkpoint('tenant_ready',location=location)
        original='SRC_A_'+suffix
        replacement='SRC_B_'+suffix
        for src in (original,replacement):
            h.ok(endpoint,'AdminSvr','tenantDataSourceAdmin',{
                'action':'CREATE','location':location,'cid':'CREATE_'+src,
                'data_source_id':src,'source_name':'QA '+src,
                'source_type':'CUSTOM','source_symbol':src},admin_token)
        h.ok(endpoint,'AdminSvr','tenantProductDataSource',{
            'action':'CREATE','location':location,'cid':'PRODUCT_'+suffix,
            'security_id':'BTC003USDT','product_name':'Source TTL QA product',
            'data_source_id':original,'template_security_id':'BTCUSDT',
            'matching_mode':'ORDER_ONLY'},admin_token)
        checkpoint('sources_and_product_created',product='BTC003USDT')
        broker=h.ok(endpoint,'LoginSvr','tenantApiKeyAdmin',{
            'action':'CREATE','type':'broker','label':'ttl-qa-'+suffix,
            'cid':'BROKER_SOURCE_'+suffix},admin_token)
        broker_key=broker['api_key']
        for attempt in range(30):
            try:
                token=h.signed_login(endpoint,broker['api_key'],broker['secret_key'],location)['token']
                break
            except RuntimeError as error:
                if not any(x in str(error) for x in ('code=7000','code=7004')) or attempt==29:
                    raise
                time.sleep(3)
        checkpoint('broker_authenticated',attempts=attempt+1)
        def publish(source,mark,seq,ttl_ms):
            return h.ok(endpoint,'APSSvr','publishBrokerPrice',{
                'location':location,'data_source_id':source,'market_indicator':'4',
                'index_price':str(int(mark)-1),'mark_price':str(mark),
                'source_time_ms':int(time.time()*1000),'ttl_ms':ttl_ms,
                'config_version':1,'sequence':seq,
                'cid':'PUBLISH_'+suffix+'_'+source+'_'+str(seq)},token)
        def market_mark():
            reply=h.call(endpoint,'MDSvr','queryPublicMarket',{
                'location':location,'securityID':'BTC003USDT'})
            if reply.get('code')!=0:return '__NOT_READY__'
            return ((reply.get('data') or {}).get('ticker') or {}).get('MarkPrice')
        def wait_mark(expected,limit,reason):
            previous=None
            for _ in range(limit*2):
                previous=market_mark()
                if previous==expected:return
                time.sleep(0.5)
            raise AssertionError(reason+'; observed='+str(previous)[:50])
        publish(original,90001,1,60000)
        # New Admin/MD symbol catalog is propagated asynchronously. Refreshing
        # an identical *price event* with a new increasing sequence is safe;
        # unlike an order, it does not create a business mutation.
        for tick in range(100):
            observed=market_mark()
            if observed=='90001':break
            if tick and tick%10==0:
                publish(original,90001,1+tick//10,60000)
            time.sleep(0.5)
        else:
            raise AssertionError('Original source never reached MD; last='+str(observed))
        checkpoint('source_a_live',mark='90001',probes=tick+1)
        rebound=h.ok(endpoint,'AdminSvr','tenantProductDataSource',{
            'action':'BIND','location':location,'cid':'BIND_B_'+suffix,
            'security_id':'BTC003USDT','data_source_id':replacement},admin_token)
        if rebound.get('data_source_id')!=replacement:
            raise AssertionError('Source BIND response mismatch')
        wait_mark(None,55,'Former source still visible after BIND')
        checkpoint('source_a_revoked_after_bind',refresh=rebound.get('query_symbol_refresh'))
        publish(original,92000,2,60000)
        time.sleep(2)
        if market_mark() is not None:
            raise AssertionError('Former source leaked into rebound product')
        checkpoint('old_source_postbind_publish_ignored')
        # A >1% jump is intentional and should be accepted if the quote is fresh.
        publish(replacement,110000,1,15000)
        wait_mark('110000',10,'New source mark not visible; >1% jump blocked')
        checkpoint('source_b_live',mark='110000',delta_from_old_percent='22.22',ttl_ms=15000)
        wait_mark(None,32,'Expired mark stayed live or fell back to old source')
        checkpoint('source_b_expired_no_fallback')
        return 0
    except Exception as error:
        checkpoint('FAILED',type=type(error).__name__,message=str(error)[:190])
        return 1
    finally:
        if broker_key and admin_token:
            try:
                response=h.call(endpoint,'LoginSvr','tenantApiKeyAdmin',{
                    'action':'DELETE','api_key':broker_key,'cid':'REVOKE_'+suffix},admin_token)
                checkpoint('broker_key_revoked',code=response.get('code'))
            except Exception as error:
                checkpoint('broker_key_revocation_failed',type=type(error).__name__)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Required to mutate isolated Demo tenant')
    parser.add_argument('--endpoint',default='http://127.0.0.1:33002/httpapi/')
    args=parser.parse_args()
    if not args.execute:parser.error('refusing mutations without --execute')
    sys.exit(run(h.require_local(args.endpoint)))
