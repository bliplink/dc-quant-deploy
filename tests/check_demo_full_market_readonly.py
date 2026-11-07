#!/usr/bin/env python3
"""T542 read-only full Demo functional smoke across real Web->Gateway->MD/Trade.

No registration/order writes. Physical HA failover, complete Web UX and custom
broker-source publishing require separate active E2E, never inferred as PASS.
"""
import json
import argparse
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PERIODS = ("1M", "5M", "15M", "1H")
SHANGHAI = timezone(timedelta(hours=8))


def api(base, server, method, content, key=None):
    request = {"serverName": server, "method": method, "content": content}
    if key is not None:
        request["key"] = key
    data = json.dumps(request, separators=(",", ":")).encode()
    with urlopen(Request(base, data=data, headers={"Content-Type": "application/json"}), timeout=12) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("code") != 0:
        raise ValueError("API_ERROR_%s_%s" % (server, method))
    return result.get("data")


def parse_bars(rows, period):
    if not isinstance(rows, list):
        raise ValueError("KLINE_RESPONSE_NOT_LIST")
    seen = set()
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 7:
            raise ValueError("KLINE_FIELDS_MISSING")
        stamp = int(parts[1])
        if stamp <= 1500000000000 or stamp in seen:
            raise ValueError("KLINE_BAD_EPOCH_OR_DUPLICATE")
        seen.add(stamp)
        open_, high, low, close, volume = [float(x) for x in parts[2:7]]
        if min(open_, high, low, close) <= 0 or low > min(open_, close) or high < max(open_, close) or volume < 0:
            raise ValueError("KLINE_OHLC_INVARIANT_FAILED")
    if not rows:
        raise ValueError("KLINE_NO_HISTORY_" + period)
    return len(rows), max(seen)


def test_location(base, location, symbol):
    catalog = api(base, "AdminSvr", "querySymbol", {"location": location}) or {}
    products = catalog.get("symbols", []) if isinstance(catalog, dict) else []
    active = [x["symbol"] for x in products if x.get("activity", "1") == "1" and x.get("symbol")]
    if symbol not in active:
        raise ValueError("SYMBOL_NOT_PUBLIC_ACTIVE")

    market = api(base, "MDSvr", "queryPublicMarket",
                 {"location": location, "securityID": symbol},
                 "%s\x1f4\x1f%s" % (location, symbol))
    if not isinstance(market, dict) or market.get("location") != location:
        raise ValueError("WRONG_TENANT_MARKET")
    book = (market.get("orderBook") or {}).get("NoMDEntries") or []
    recent = (market.get("recentTrades") or {}).get("NoMDEntries") or []
    ticker = market.get("ticker") or {}
    bids = sum(str(x.get("MDEntryType")) == "0" for x in book)
    asks = sum(str(x.get("MDEntryType")) == "1" for x in book)
    if bids < 10 or asks < 10:
        raise ValueError("DEPTH_MISSING")
    if not recent or any(not x.get("MDEntryTime") or not x.get("MDEntryID") for x in recent[:10]):
        raise ValueError("RECENT_TRADE_TIME_OR_ID_MISSING")
    for key in ["LastPrice", "MarkPrice", "IndexPrice", "HighPrice", "LowPrice", "OpenPrice", "Turnover", "Volume"]:
        if key not in ticker or float(ticker[key]) <= 0:
            raise ValueError("TICKER_INVALID_" + key)
    if float(ticker["HighPrice"]) < float(ticker["LowPrice"]):
        raise ValueError("TICKER_HIGH_BELOW_LOW")

    now = datetime.now(SHANGHAI)
    content = {"location": location, "securityID": symbol, "num": 200,
               "start": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
               "end": now.strftime("%Y-%m-%d %H:%M:%S")}
    counts = {}
    latest = {}
    for period in PERIODS:
        rows = api(base, "AdminSvr", "queryKLine", dict(content, text=period))
        counts[period], latest[period] = parse_bars(rows, period)
    if abs(datetime.now(timezone.utc).timestamp()*1000 - latest["5M"]) > 15*60*1000:
        raise ValueError("KLINE_5M_STALE")
    default = active[0] if active else ""
    default_bars = api(base, "AdminSvr", "queryKLine", dict(content, text="5M", securityID=default))
    return {
        "products": active, "bid_levels": bids, "ask_levels": asks,
        "recent_trades": len(recent), "ticker_fields": 8,
        "kline_periods": counts, "default_symbol": default,
        "default_symbol_5m_bars": len(default_bars or []),
        "last_mark": ticker.get("MarkPrice"), "last_index": ticker.get("IndexPrice")
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18088/httpapi/")
    p.add_argument("--locations", default="A2I12Z,AGKW5V,BML3DA,CN8U7C,J4BMAH,RU7WZO")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--frontends", default="18088,18090,18092,18094")
    args = p.parse_args()
    locations = [x for x in args.locations.split(",") if x]
    results, errors, notes = {}, [], []
    for location in locations:
        try:
            result = test_location(args.url, location, args.symbol)
            results[location] = result
            if not result["default_symbol_5m_bars"]:
                notes.append("DEFAULT_PRODUCT_NO_KLINE:" + location + ":" + result["default_symbol"])
        except (ValueError, HTTPError, URLError, TimeoutError, TypeError, KeyError) as error:
            errors.append(location + ":" + str(error)[:110])
    for port in args.frontends.split(","):
        try:
            rows = api("http://127.0.0.1:%d/httpapi/" % int(port), "AdminSvr", "queryKLine",
                       {"location": locations[0], "securityID": args.symbol, "text": "5M", "num": 20})
            if not rows:
                raise ValueError("FRONTEND_ROUTE_STALE")
        except (ValueError, HTTPError, URLError, TimeoutError) as error:
            errors.append("FRONTEND_" + port + ":" + str(error)[:100])
    print(json.dumps({
        "status": ("NO_GO" if errors else ("PARTIAL_DEFAULT_KLINE_NO_GO" if notes
                    else "PASS_READONLY_MARKET_API_NOT_COMPLETE_E2E")),
        "location_count": len(locations), "location_pass": len(results),
        "results": results, "warnings": notes, "failures": errors,
        "full_trader_broker_write_e2e_verified": False,
        "authenticated_web_ux_verified": False, "ha_sigkill_verified": False,
    }, ensure_ascii=False, sort_keys=True))
    if errors:
        raise SystemExit(2)
    if notes:
        # An anonymous user's first-selected product is the real first chart;
        # passing the alternative BTCUSDT alone is insufficient for UX PASS.
        raise SystemExit(3)


if __name__ == "__main__":
    main()