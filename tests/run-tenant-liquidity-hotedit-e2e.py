#!/usr/bin/env python3
"""Verify a new Demo tenant can hot-apply liquidity profiles without Robot restart.

Export the protected local deploy env before running. This creates one trial
tenant. Mutations use Manager/Admin/Login APIs; SQL is only for convergence.
"""

import importlib.util
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path


path = Path(__file__).with_name("run-auto-tenant-trading-e2e.py")
spec = importlib.util.spec_from_file_location("tenant_e2e", path)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def robot_state(location):
    rows = api.sql("SELECT bid_levels,ask_levels,enabled,runtime_status,open_order_count "
                   "FROM dc_tenant_robot WHERE location='%s'" % location)
    return rows[0] if len(rows) == 1 else rows


def profile(levels, zones):
    return json.dumps({
        "bid_levels": levels, "ask_levels": levels,
        "level_spread_bps": "5", "level_step_bps": "2",
        "order_qty": "0.001", "max_position_qty": "0.1",
        "refresh_interval_ms": 1000, "stale_price_ms": 5000,
        "max_deviation_bps": "500", "circuit_breaker_seconds": 30,
        "quote_mode": "FIXED", "depth_quantity_mode": "NOTIONAL_ZONES",
        "depth_margin_budget": "1000", "depth_leverage": "1",
        "depth_zone_levels": zones, "depth_zone_weights": [3, 3, 4],
        "sweep_user_orders_enabled": False, "tape_enabled": False,
    })


def apply_profile(location, token, profile_id, robot_id, levels, zones, run_id):
    response = api.call("AdminSvr", "tenantLiquidityProfileAdmin", {
        "action": "UPSERT", "location": location,
        "cid": "HOT_PROFILE_%s_%d" % (run_id, levels),
        "request_id": "HOT_PROFILE_%s_%d" % (run_id, levels),
        "profile_id": profile_id, "profile_name": "Demo 40-Level Liquidity",
        "description": "Temporary hot-edit acceptance profile",
        "profile_config": profile(levels, zones),
    }, token)
    profile_id = response["profile_id"]
    api.call("AdminSvr", "tenantLiquidityProfileAdmin", {
        "action": "APPLY", "location": location,
        "cid": "HOT_APPLY_%s_%d" % (run_id, levels),
        "request_id": "HOT_APPLY_%s_%d" % (run_id, levels),
        "profile_id": profile_id, "robot_id": robot_id,
    }, token)
    expected = [str(levels), str(levels), "1", "RUNNING", str(levels * 2)]
    api.wait("Robot hot-apply %d+%d" % (levels, levels),
             lambda: (state if (state := robot_state(location)) == expected else None),
             seconds=90, interval=0.5)
    return profile_id


def container_id():
    return subprocess.run(["docker", "inspect", "-f", "{{.Id}}", "dc-saas-robotsvr"],
                          capture_output=True, text=True, timeout=10, check=True).stdout.strip()


def main():
    active = int(api.sql("SELECT COUNT(*) FROM dc_tenant WHERE status IN ('ACTIVE','TRIAL')")[0][0])
    if active >= 200:
        raise RuntimeError("Auto-approval safety gate reached: %d active tenants" % active)
    run_id = time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()
    password = secrets.token_urlsafe(24)
    email = "hotedit-" + run_id.lower() + "@example.invalid"
    submission = api.call("ManagerSvr", "tenantApplication", {
        "action": "SUBMIT", "cid": "HOT_TENANT_" + run_id,
        "request_id": "HOT_TENANT_" + run_id,
        "organization_name": "Hot Edit Acceptance " + run_id,
        "contact_name": "Hot Edit Tester", "contact_email": email,
        "expected_users": 2, "requested_symbols": ["BTCUSDT"],
        "requested_trial_days": 30, "admin_password": password,
    })
    status = api.call("ManagerSvr", "tenantApplication", {
        "action": "STATUS", "application_id": submission["application_id"],
        "contact_email": email,
    })
    if status.get("status") != "APPROVED":
        raise RuntimeError("Trial was not auto-approved: %s" % status.get("status"))
    location = status["approved_location"]
    print("[liquidity-hotedit] location=%s auto-approved" % location, flush=True)
    api.wait("automatic 40-order liquidity bootstrap", lambda:
             True if api.sql("SELECT status,funding_confirmed FROM dc_tenant_liquidity_bootstrap "
                             "WHERE location='%s'" % location) == [["COMPLETE", "1"]]
             and robot_state(location) == ["20", "20", "1", "RUNNING", "40"] else None,
             seconds=240, interval=2)
    api.LOCATION = location
    if tuple(map(len, api.market_book())) != (10, 10):
        raise RuntimeError("Public top-ten book is not 10+10")
    login = api.call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "HOT_LOGIN_" + run_id,
        "user_id": "tenantadmin", "user_name": "tenantadmin",
        "password": password, "client_type": "TenantAdmin", "Location": location,
    })
    token = login["token"]
    robot_id = api.sql("SELECT robot_id FROM dc_tenant_robot WHERE location='%s'" % location)[0][0]
    original_container = container_id()
    profile_id = "hotedit-" + run_id
    try:
        apply_profile(location, token, profile_id, robot_id,
                      15, [5, 5, 5], run_id)
        print("[liquidity-hotedit] applied 15+15 without service restart", flush=True)
    finally:
        apply_profile(location, token, profile_id, robot_id,
                      20, [6, 6, 8], run_id)
    if container_id() != original_container:
        raise RuntimeError("Robot container restarted during profile apply")
    if tuple(map(len, api.market_book())) != (10, 10):
        raise RuntimeError("Public top-ten book did not return after restoring 20+20")
    print("[liquidity-hotedit] PASS location=%s profile=%s final=20+20 open=40 container_unchanged=true" %
          (location, profile_id), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[liquidity-hotedit] FAIL: %s" % exc, file=sys.stderr, flush=True)
        sys.exit(1)
