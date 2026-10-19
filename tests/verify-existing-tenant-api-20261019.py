#!/usr/bin/env python3
"""Read-only Gateway API acceptance: public response and private auth fence."""
import argparse
import json
import pathlib
import stat
import urllib.request

def post(base, server, method, content, route=None):
    payload={"serverName":server,"method":method,"content":content}
    if route:payload["key"]=route
    req=urllib.request.Request(base.rstrip("/")+"/httpapi/",
        json.dumps(payload).encode(),{"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=12) as response:
        return json.load(response)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--tenant",default="GW7XMI")
    p.add_argument("--base",default="http://127.0.0.1:18088")
    p.add_argument("--credentials-file",type=pathlib.Path)
    p.add_argument("--require-book",action="store_true",help="Fail when depth is empty")
    a=p.parse_args()
    tenant=a.tenant.upper()
    if not tenant.isascii() or not tenant.isalnum():p.error("invalid tenant")
    key=tenant+"\x1f4\x1fBTCUSDT"
    public=post(a.base,"AdminSvr","publicTenantDirectory",{})
    assert str(public.get("code"))=="0", "public tenant directory unavailable"
    print("PASS publicTenantDirectory")
    market=post(a.base,"MDSvr","queryPublicMarket",
        {"location":tenant,"securityID":"BTCUSDT"},key)
    assert str(market.get("code"))=="0", "public market unavailable"
    entries=((market.get("data") or {}).get("orderBook") or {}).get("NoMDEntries") or []
    print("PASS publicMarket", "bookEntries="+str(len(entries)))
    if a.require_book and not entries:
        raise RuntimeError("public market has no depth for the requested tenant")
    protected=[
        ("AdminSvr","queryOrder",{},None),
        ("AdminSvr","queryExecOrder",{},None),
        ("TradeSvr","queryAccountBalance",{},tenant),
        ("TradeSvr","queryTradePosition",{},tenant),
        ("OrderSvr","queryOpenOrder",{"securityid":"BTCUSDT"},key),
        ("APSSvr","publishBrokerPrice",{},None),
    ]
    for server,method,content,route in protected:
        out=post(a.base,server,method,content,route)
        assert str(out.get("code"))=="10004",server+"/"+method+" anonymous guard mismatch"
        print("PASS anonymousDenied",server+"/"+method)
    if not a.credentials_file:
        print("NOT_RUN authenticatedTraderAPI (requires dedicated existing-tenant key)")
        return
    perms=a.credentials_file.stat().st_mode
    if perms & (stat.S_IRWXG|stat.S_IRWXO):
        raise RuntimeError("credentials file must be chmod 600")
    identity=json.loads(a.credentials_file.read_text())
    if identity["location"].upper()!=tenant:
        raise RuntimeError("credentials tenant mismatch")
    from opentradingcore import OpenTradingCoreClient
    sdk=OpenTradingCoreClient.from_api_key(base_url=a.base,location=tenant,
        api_key=identity["api_key"],api_secret=identity["api_secret"],timeout=12)
    session=sdk.login(mode="trader")
    assert session.location==tenant and session.client_type=="API"
    print("PASS TraderAPI signedLogin")
    for name,func in [
        ("market",lambda:sdk.market_snapshot("BTCUSDT")),
        ("kline",lambda:sdk.kline("BTCUSDT",limit=5)),
        ("openOrders",lambda:sdk.open_orders("BTCUSDT")),
        ("balances",sdk.balances),
        ("positions",sdk.positions),
        ("orders",lambda:sdk.order_history(page_size=5)),
        ("executions",lambda:sdk.execution_history(page_size=5)),
    ]:
        func()
        print("PASS TraderAPI",name)
    print("NOT_RUN orderWriteCancelMatch (this script never sends writes)")

if __name__=="__main__":
    main()

