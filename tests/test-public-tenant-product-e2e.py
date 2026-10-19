#!/usr/bin/env python3
"""Read-only Demo acceptance for public tenant products and anonymous Trading Web.

Uses only Python standard library + Playwright. Does not register tenants,
log in, modify product configuration, or submit a financial transaction.
"""
import argparse
import json
import sys
import urllib.request

def post(base, server, method, content):
    target = base.rstrip("/") + "/httpapi/"
    payload = json.dumps({"serverName":server, "method":method, "content":content}).encode()
    req = urllib.request.Request(target, data=payload,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=15) as result:
        return json.load(result)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway",default="http://127.0.0.1:33002")
    parser.add_argument("--tenant-web",default="http://127.0.0.1:18092")
    parser.add_argument("--trade-web",default="http://127.0.0.1:18088")
    parser.add_argument("--tenant",action="append",required=True)
    parser.add_argument("--api-only",action="store_true",
                        help="Run read-only Gateway/MD checks without launching a browser")
    parser.add_argument("--hidden",action="append",default=[],
                        help="A disabled product code that MUST NOT appear")
    parser.add_argument("--expect",action="append",default=[],
                        help="An enabled product code that MUST be visible")
    parser.add_argument("--require-null-mark",action="append",default=[],
                        help="A public product whose expired/unbound MarkPrice and IndexPrice must be null")
    args=parser.parse_args()
    findings=[]
    for tenant in args.tenant:
        result=post(args.gateway,"AdminSvr","querySymbol",{"location":tenant})
        assert result["code"]==0,(tenant,result)
        rows=(result.get("data") or {}).get("symbols")
        assert isinstance(rows,list),(tenant,rows)
        assert all(row.get("activity")=="1" and row.get("expiried")=="0" for row in rows)
        visible=[row["symbol"] for row in rows]
        assert not set(visible).intersection(args.hidden),(tenant,visible)
        assert set(args.expect).issubset(set(visible)),(tenant,visible,args.expect)
        # The public MD snapshot must also reject disabled products; an empty
        # SUCCESS placeholder leaks a false tradable market into Web clients.
        for disabled in args.hidden:
            market=post(args.gateway,"MDSvr","queryPublicMarket",
                        {"location":tenant,"securityID":disabled})
            assert market.get("code")==5004,(tenant,disabled,market)
        # Prevent a cached pre-switch/custom quote outliving its declared TTL
        # on the externally visible MD snapshot. No risk of writing test data.
        for product in args.require_null_mark:
            market=post(args.gateway,"MDSvr","queryPublicMarket",
                        {"location":tenant,"securityID":product})
            assert market.get("code")==0,(tenant,product,market.get("code"))
            ticker=(market.get("data") or {}).get("ticker") or {}
            assert ticker.get("MarkPrice") is None,(tenant,product,"stale_mark_returned")
            assert ticker.get("IndexPrice") is None,(tenant,product,"stale_index_returned")
        if visible:
            symbol=visible[0]
            market=post(args.gateway,"MDSvr","queryPublicMarket",
                        {"location":tenant,"securityID":symbol})
            assert market.get("code")==0,(tenant,symbol,market)
            snapshot=market.get("data") or {}
            assert snapshot.get("location")==tenant,(tenant,snapshot.get("location"))
            assert snapshot.get("securityID")==symbol,(tenant,snapshot.get("securityID"))
            assert "orderBook" in snapshot and "ticker" in snapshot and "recentTrades" in snapshot
            findings.append({"tenant":tenant,"visible":visible,"enabled":len(visible),
                             "public_market_http_api":0,
                             "book_entries":len((snapshot.get("orderBook") or {}).get("NoMDEntries") or [])})
        else:
            findings.append({"tenant":tenant,"visible":[],"enabled":0})
    admin=post(args.gateway,"AdminSvr","tenantProductDataSource",{"action":"LIST","location":args.tenant[0]})
    assert admin.get("code")==10004,admin
    findings.append({"unscoped_administrative_list":"AUTHENTICATED_SESSION_REQUIRED"})
    if args.api_only:
        print(json.dumps({"api_checks":findings,"browser_checks":[],"mode":"api-only"},
                         ensure_ascii=False,sort_keys=True))
        return 0
    from playwright.sync_api import sync_playwright
    browser_checks=[]
    tenant=args.tenant[0]
    with sync_playwright() as pw:
        from pathlib import Path as _Path
        chrome=_Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        browser=pw.chromium.launch(headless=True, **(
            {"executable_path":str(chrome)} if chrome.is_file() else {}))
        for width in (1440,390):
            page=browser.new_page(viewport={"width":width,"height":850})
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            snapshots=[]
            def capture_public_market(reply):
                if "/httpapi/" not in reply.url or reply.request.method!="POST":return
                try:
                    request=reply.request.post_data_json or {}
                    if request.get("method")=="queryPublicMarket":
                        response=reply.json()
                        data=response.get("data") or {}
                        snapshots.append((reply.status,response.get("code"),
                                          data.get("location"),data.get("securityID")))
                except Exception:pass
            page.on("response",capture_public_market)
            response=page.goto(args.trade_web.rstrip("/")+
                "/#/trade?location="+tenant,wait_until="domcontentloaded",timeout=25000)
            page.locator(".tradeWrap").wait_for(timeout=30000)
            page.locator(".publicActions").wait_for(timeout=15000)
            assert response.status==200
            assert "/login" not in page.url
            assert not errors,errors
            # Drawer exists off-screen by default. Checking body.innerText or
            # clicking an off-screen drawer row is not evidence of user-facing
            # navigation. Open the actual symbol selector and choose a product.
            target=(args.expect or visible)[0]
            page.locator(".symbolDiv.cp").first.click(timeout=15000)
            market_item=page.get_by_text(target,exact=True).first
            market_item.wait_for(timeout=16000)
            market_item.click(timeout=12000)
            page.wait_for_function(
                "code => document.querySelector('.symbolCode')?.textContent?.includes(code)",
                arg=target, timeout=12000)
            page.wait_for_timeout(2000)
            matches=[s for s in snapshots if s[:3]==(200,0,tenant) and s[3]==target]
            assert matches,(target,snapshots)
            assert not errors,errors
            browser_checks.append({"viewport":width,"http":response.status,
                                   "public":True,"selected_product":target,
                                   "public_md_snapshot":matches[-1],"js_errors":0})
            page.close()
        browser.close()
    print(json.dumps({"api_checks":findings,"browser_checks":browser_checks},
                     ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except Exception as exc:
        print("E2E_FAILED:",repr(exc),file=sys.stderr)
        sys.exit(1)
