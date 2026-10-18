#!/usr/bin/env python3
"""Exercise already-issued tenant sessions across a platform suspension."""

import json
import os
import secrets
import time
import urllib.request

URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:18088/httpapi/")


def call(server, method, content, token=None):
    body = json.dumps({"serverName": server, "method": method, "content": content}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["sessionId"] = token
    request = urllib.request.Request(URL, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def require_ok(response, stage):
    if response.get("code") != 0:
        raise AssertionError(f"{stage}: {response.get('msg')}")
    return response["data"]


def login(username, password, client_type, location):
    return require_ok(call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "SUSPEND_SESSION_E2E", "user_id": username,
        "user_name": username, "password": password,
        "client_type": client_type, "Location": location,
    }), "login")


def main():
    readiness = call("AdminSvr", "tenantSettingsAdmin", {"action": "GET", "cid": "READINESS"})
    if readiness.get("code") == 1003:
        raise AssertionError("AdminSvr is not online; refusing to create a test tenant")
    stamp = str(int(time.time() * 1000))
    password = secrets.token_urlsafe(20)
    email = f"suspend-{stamp}@acceptance.invalid"
    application = require_ok(call("ManagerSvr", "tenantApplication", {
        "action": "SUBMIT", "cid": stamp, "request_id": "SUSPEND_SESSION_" + stamp,
        "organization_name": "Suspension Session Acceptance " + stamp,
        "contact_name": "Acceptance", "contact_email": email,
        "admin_password": password,
    }), "submit")
    if application.get("status") != "APPROVED":
        raise AssertionError("test tenant was not auto-approved")
    location = application["approved_location"]
    admin = login("tenantadmin", password, "TenantAdmin", location)
    admin_token = admin["token"]
    settings = {"action": "GET", "location": location, "cid": stamp}
    require_ok(call("AdminSvr", "tenantSettingsAdmin", settings, admin_token), "settings before suspend")
    trader_password = secrets.token_urlsafe(20)
    require_ok(call("AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "cid": stamp, "request_id": "TRADER_" + stamp,
        "location": location, "username": "suspendtrader", "name": "Suspension Trader",
        "email": f"trader-{stamp}@acceptance.invalid", "password": trader_password,
    }), "register trader")
    trader = login("suspendtrader", trader_password, "WEB", location)
    trader_token = trader["token"]
    trader_query = {"cid": stamp}
    require_ok(call("LoginSvr", "queryApiKey", trader_query, trader_token), "trader session before suspend")
    platform = login(os.environ["PLATFORM_ADMIN_USERNAME"], os.environ["PLATFORM_ADMIN_PASSWORD"],
                     "Manager", "PLATFORM")
    platform_token = platform["token"]
    try:
        require_ok(call("ManagerSvr", "tenantApproval", {
            "action": "UPDATE_TENANT", "cid": stamp, "request_id": "SUSPEND_" + stamp,
            "location": location, "status": "SUSPENDED",
        }, platform_token), "suspend")
        stale = call("AdminSvr", "tenantSettingsAdmin", settings, admin_token)
        if stale.get("code") == 0:
            raise AssertionError("existing tenant admin session still works after suspension")
        stale_trader = call("LoginSvr", "queryApiKey", trader_query, trader_token)
        if stale_trader.get("code") == 0:
            raise AssertionError("existing trader session still works after suspension")
        print(json.dumps({"result": "PASS", "location": location,
                          "existingAdminSessionDenied": True,
                          "existingTraderSessionDenied": True,
                          "adminDenialCode": stale.get("code"),
                          "traderDenialCode": stale_trader.get("code")}))
    finally:
        require_ok(call("ManagerSvr", "tenantApproval", {
            "action": "UPDATE_TENANT", "cid": stamp, "request_id": "RESUME_" + stamp,
            "location": location, "status": "ACTIVE", "registration_enabled": True,
            "trade_enabled": True,
        }, platform_token), "reactivate")


if __name__ == "__main__":
    main()
