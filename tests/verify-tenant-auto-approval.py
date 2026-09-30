#!/usr/bin/env python3
"""Small public API acceptance for automatic and manual tenant-review paths."""

import json
import os
import secrets
import time
import urllib.request
from datetime import datetime

ENDPOINT = "http://127.0.0.1:18088/httpapi/"


def call(server, method, content):
    body = json.dumps({"serverName": server, "method": method, "content": content}).encode()
    request = urllib.request.Request(
        ENDPOINT, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get("code") != 0:
        raise RuntimeError(f"{server}.{method}: {result.get('msg')}")
    return result.get("data")


def main():
    suffix = datetime.now().strftime("%m%d%H%M%S")
    password = os.environ.get("TENANT_APPLICATION_TEST_PASSWORD") or secrets.token_urlsafe(18)
    email = f"auto-tenant-{suffix}@acceptance.invalid"
    application = {
        "action": "SUBMIT",
        "cid": f"AUTO_E2E_{suffix}",
        "request_id": f"AUTO_E2E_{suffix}",
        "organization_name": f"Auto Tenant Acceptance {suffix}",
        "contact_name": "Acceptance",
        "contact_email": email,
        "expected_users": 3,
        "admin_password": password,
    }
    for attempt in range(90):
        try:
            auto = call("ManagerSvr", "tenantApplication", application)
            break
        except RuntimeError as error:
            if "not Online" not in str(error) or attempt == 89:
                raise
            time.sleep(1)
    assert auto["status"] == "APPROVED", auto
    location = auto["approved_location"]
    assert location and auto["admin_console_url"].endswith(location), auto
    status = call("ManagerSvr", "tenantApplication", {
        "action": "STATUS", "application_id": auto["application_id"], "contact_email": email
    })
    assert status["status"] == "APPROVED" and status["approved_location"] == location
    idempotent = call("ManagerSvr", "tenantApplication", application)
    assert idempotent["application_id"] == auto["application_id"]
    assert idempotent["idempotent"] is True
    login = call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": f"AUTO_LOGIN_{suffix}",
        "user_id": "tenantadmin", "user_name": "tenantadmin", "password": password,
        "client_type": "TenantAdmin", "Location": location,
    })
    assert login["token"] and login["location"] == location
    pending = call("ManagerSvr", "tenantApplication", {
        "action": "SUBMIT", "cid": f"MANUAL_E2E_{suffix}",
        "request_id": f"MANUAL_E2E_{suffix}",
        "organization_name": f"Manual Review Acceptance {suffix}",
        "contact_name": "Acceptance",
        "contact_email": f"manual-tenant-{suffix}@acceptance.invalid",
        "expected_users": 3,
        "requested_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "UNIUSDT", "XRPUSDT"],
        "admin_password": password,
    })
    assert pending["status"] == "PENDING" and not pending.get("approved_location")
    print(json.dumps({
        "result": "PASS", "auto_application": auto["application_id"],
        "auto_location": location, "default_symbol": "BTCUSDT",
        "idempotent": idempotent["idempotent"], "admin_login": "PASS",
        "five_symbol_application": pending["application_id"],
        "five_symbol_status": pending["status"],
    }))


if __name__ == "__main__":
    main()
