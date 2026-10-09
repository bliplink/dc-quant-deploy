#!/usr/bin/env python3
"""Fill or validate the OpenTradingCore GW partition routing key.

Runs only on a provided JSON envelope. It never contacts the network, opens
credentials, signs requests, or changes customer accounts.
"""
import json
import re
import sys

PARTITIONED_SERVICES = frozenset(("OrderSvr", "MDSvr"))
LOCATION = re.compile(r"^[A-Z0-9_-]{1,64}$")
SYMBOL = re.compile(r"^[A-Z0-9_-]{1,40}$")
MARKET = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def apply_route(envelope, default_location):
    if not isinstance(envelope, dict):
        raise ValueError("GW request must be a JSON object")
    if envelope.get("serverName") not in PARTITIONED_SERVICES:
        return envelope

    content = envelope.get("content")
    if not isinstance(content, dict):
        raise ValueError("partitioned GW request requires content object")
    location = content.get("Location") or content.get("location") or default_location
    symbol = (
        content.get("SecurityID") or content.get("securityID") or content.get("securityid")
    )
    market = content.get("MarketIndicator") or content.get("marketIndicator") or "4"
    if not isinstance(location, str) or not LOCATION.fullmatch(location):
        raise ValueError("invalid GW partition location")
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        raise ValueError("partitioned GW request requires SecurityID")
    market = str(market)
    if not MARKET.fullmatch(market):
        raise ValueError("invalid GW market indicator")
    expected_key = location + "\x1f" + market + "\x1f" + symbol

    supplied = envelope.get("key")
    if supplied is not None and supplied != expected_key:
        raise ValueError("GW partition key disagrees with request target")
    envelope["key"] = expected_key
    return envelope


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: gw-partition-route.py DEFAULT_TENANT_LOCATION")
    try:
        data = json.load(sys.stdin)
        route = apply_route(data, sys.argv[1])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        # Never echo request bodies, tokens or secrets into CI logs.
        print("GW routing validation failed: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
    sys.stdout.write(json.dumps(route, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
