#!/usr/bin/env python3
"""Non-mutating acceptance for an EXISTING authorized Broker API Key.

No key issuance, revocation, orders, tenant changes, or money movements.
Only callable with a previously provisioned disposable Broker test key.
Never prints the secret, API key, token or account data.
"""
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

PUBLIC_READ_METHODS = frozenset({
    ("MDSvr", "queryPublicMarket"),
    ("TradeSvr", "queryAccountBalance"),
    ("AdminSvr", "queryOrder"),
    ("AdminSvr", "queryExecOrder"),
})
ADMIN_DENIAL_METHODS = frozenset({
    ("AdminSvr", "tenantTradeAdmin"),
    ("LoginSvr", "tenantApiKeyAdmin"),
})
ALLOWED_METHODS = PUBLIC_READ_METHODS | ADMIN_DENIAL_METHODS | {("LoginSvr", "apiKeyLogin")}
BROKER_SCOPES = frozenset({"MARKET_READ", "ACCOUNT_READ", "ORDER_READ", "ORDER_WRITE"})


class ContractError(RuntimeError):
    pass


def body_bytes(server, method, content, key=None):
    if (server, method) not in ALLOWED_METHODS:
        raise ContractError("Unsafe method not permitted by read-only acceptance")
    if (server, method) == ("LoginSvr", "tenantApiKeyAdmin") and content.get("action") != "LIST":
        raise ContractError("Only API Key LIST (denial test) is allowed")
    if (server, method) == ("AdminSvr", "tenantTradeAdmin") and content.get("action") != "BALANCES":
        raise ContractError("Only tenant BALANCES (denial test) is allowed")
    body = {"serverName": server, "method": method}
    if key is not None:
        body["key"] = key
    body["content"] = content
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(secret, body, expiry):
    return hmac.new(secret.encode(), body + expiry.encode("ascii"), hashlib.sha256).hexdigest()


def gateway_call(base, server, method, content, headers=None, key=None):
    route = "/api" if (server, method) == ("LoginSvr", "apiKeyLogin") else "/httpapi/"
    raw = body_bytes(server, method, content, key)
    request = urllib.request.Request(
        base + route, data=raw,
        headers={"Content-Type": "application/json", "User-Agent": "OpenTradingCore-Broker-Readonly-QA/1.0",
                 **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.loads(response.read(1024 * 1024))
        return str(result.get("code", "")), result.get("data") or {}
    except urllib.error.HTTPError as e:
        # Read no error body: edge pages can include secrets or user metadata.
        return "HTTP_" + str(e.code), {}


def require(condition, message):
    if not condition:
        raise ContractError(message)


def run():
    names = ("OTC_BROKER_QA_KEY", "OTC_BROKER_QA_SECRET", "OTC_BROKER_QA_LOCATION",
             "OTC_BROKER_QA_CUSTOMER_ID")
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise ContractError("Missing existing QA credentials: " + ", ".join(missing))
    base = os.getenv("OTC_BROKER_QA_GATEWAY", "http://127.0.0.1:18088").rstrip("/")
    require(base.startswith("https://") or base.startswith("http://127.0.0.1:")
            or base.startswith("http://localhost:"), "Remote HTTP must use HTTPS")
    location = os.environ["OTC_BROKER_QA_LOCATION"]
    require(re.fullmatch("[A-Za-z0-9]{3,16}", location) is not None, "Invalid tenant location")
    api_key = os.environ["OTC_BROKER_QA_KEY"]
    secret = os.environ["OTC_BROKER_QA_SECRET"]

    auth_body = body_bytes("LoginSvr", "apiKeyLogin", {
        "api_key": api_key, "location": location,
        "cid": "broker-read-qa-" + uuid.uuid4().hex[:8]
    })
    expiry = str(int(time.time() * 1000) + 60000)
    signed_headers = {
        "apikey": api_key, "expiry": expiry, "signature": sign(secret, auth_body, expiry)
    }
    code, session = gateway_call(base, "LoginSvr", "apiKeyLogin",
        json.loads(auth_body)["content"], signed_headers)
    require(code == "0", "Signed Broker login rejected (code=%s)" % code)
    require(session.get("client_type") == "TenantAPI" and
            session.get("api_key_type") == "broker", "Wrong key class")
    require(str(session.get("location", "")).upper() == location.upper(), "Wrong tenant")
    scopes = {s.strip() for s in str(session.get("permissions") or "").split(",") if s.strip()}
    require(bool(scopes) and scopes <= BROKER_SCOPES,
            "Broker session includes an undeclared admin/cash scope")
    sid = session.get("token") or session.get("sid")
    require(isinstance(sid, str) and bool(sid), "No signed session")
    headers = {"sessionId": sid}
    print("PASS signed Broker Key login and trading-only scope", flush=True)

    symbol = os.getenv("OTC_BROKER_QA_SYMBOL", "BTCUSDT")
    key = location + "\x1f4\x1f" + symbol
    if "MARKET_READ" in scopes:
        code, _ = gateway_call(base, "MDSvr", "queryPublicMarket",
            {"location": location, "securityID": symbol}, headers, key)
        require(code == "0", "Market read failed: " + code)
        print("PASS market snapshot", flush=True)
    customer_id = os.environ["OTC_BROKER_QA_CUSTOMER_ID"]
    if "ACCOUNT_READ" in scopes:
        code, _ = gateway_call(base, "TradeSvr", "queryAccountBalance",
            {"location": location, "userid": customer_id}, headers)
        require(code == "0", "Authorized account read failed: " + code)
        print("PASS authorized customer account read", flush=True)
    if "ORDER_READ" in scopes:
        for method in ("queryOrder", "queryExecOrder"):
            code, _ = gateway_call(base, "AdminSvr", method,
                {"location": location, "page_num": 0, "page_size": 2, "user_id": customer_id}, headers)
            require(code == "0", "Authorized history read failed: " + method + " " + code)
            print("PASS authorized customer history: " + method, flush=True)

    # These operations are READ-only, and must fail even for an administrator-owned Broker key.
    for server, method, content in (
        ("AdminSvr", "tenantTradeAdmin", {"action": "BALANCES", "page_num": 0, "page_size": 1}),
        ("LoginSvr", "tenantApiKeyAdmin", {"action": "LIST"}),
    ):
        code, data = gateway_call(base, server, method, content, headers)
        require(code != "0" and not data, method + " incorrectly exposed through Broker API")
        print("PASS Broker tenant-management denial: " + method, flush=True)

    foreign = os.getenv("OTC_BROKER_QA_FOREIGN_LOCATION", "").strip()
    if foreign:
        require(foreign.upper() != location.upper(), "Foreign location must differ")
        code, data = gateway_call(base, "TradeSvr", "queryAccountBalance",
            {"location": foreign, "userid": customer_id}, headers)
        require(code != "0" and not data, "Cross-tenant account query not denied")
        print("PASS cross-tenant account rejection", flush=True)
    else:
        print("SKIP cross-tenant check (no foreign QA location supplied)", flush=True)
    print("READONLY_BROKER_ACCEPTANCE_PASS (no live orders, no cash, no key changes)", flush=True)


if __name__ == "__main__":
    try:
        run()
    except (ContractError, ValueError, KeyError, urllib.error.URLError) as e:
        # Never include body/account response or credential values in error messages.
        print("READONLY_BROKER_ACCEPTANCE_FAIL", type(e).__name__,
              str(e) if isinstance(e, ContractError) else "", file=sys.stderr)
        sys.exit(1)
