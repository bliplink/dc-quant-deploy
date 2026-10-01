#!/usr/bin/env python3
"""Business-order proof across one live Order partition role reversal.

Run only after exporting the protected local deploy env and the full 256/256
Order verifier passes. This test changes exactly one ZooKeeper assignment; it
does not stop a node or claim to prove automatic failure detection.
"""

import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


source = Path(__file__).with_name("run-auto-tenant-trading-e2e.py")
spec = importlib.util.spec_from_file_location("trial_e2e", source)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

LOCATION = "EX2ENF"
SYMBOL = "BTCUSDT"
MARKET = "4"
PARTITION = "P110"
ZK_PATH = "/dc/cluster/ordersvr/partitions/" + PARTITION
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()
KEY = LOCATION + "\x1f" + MARKET + "\x1f" + SYMBOL


def log(message):
    print("[order-live-reversal] " + message, flush=True)


def zk(command):
    result = subprocess.run(
        ["docker", "exec", "-i", "dc-saas-zookeeper", "zkCli.sh", "-server", "127.0.0.1:32181"],
        input=command + "\nquit\n", text=True, capture_output=True, timeout=20,
    )
    if result.returncode:
        raise RuntimeError("ZooKeeper CLI failed")
    return result.stdout + "\n" + result.stderr


def assignment():
    output = zk("get -s " + ZK_PATH)
    rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    versions = re.findall(r"^dataVersion = (\d+)$", output, re.MULTILINE)
    if len(rows) != 1 or len(versions) != 1:
        raise RuntimeError("Cannot read one versioned partition assignment")
    return rows[0], int(versions[0])


def change_assignment(expected_epoch, primary, replica):
    current, version = assignment()
    if (current.get("partitionId") != PARTITION or current.get("state") != "READY"
            or int(current.get("epoch", 0)) != expected_epoch):
        raise RuntimeError("Assignment changed before CAS: %s" % current)
    updated = dict(current)
    updated.update({"epoch": expected_epoch + 1, "primary": primary,
                    "replica": replica, "state": "READY"})
    payload = json.dumps(updated, separators=(",", ":"))
    output = zk("set -v %d %s %s" % (version, ZK_PATH, payload))
    if "BadVersion" in output or "KeeperErrorCode" in output:
        raise RuntimeError("Versioned assignment update rejected")
    after, after_version = assignment()
    if after != updated or after_version != version + 1:
        raise RuntimeError("Assignment CAS did not converge: %s" % after)
    log("assignment epoch=%d primary=%s replica=%s" %
        (after["epoch"], primary, replica))
    return after["epoch"]


def wait_primary(node, epoch, since):
    container = "dc-saas-ordersvr" if node == "OrderSvrA" else "dc-saas-ordersvr-b"
    marker = ("ORDER_PARTITION_PROMOTION_READY node:%s, partition:%s, epoch:%d" %
              (node, PARTITION, epoch))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = subprocess.run(["docker", "logs", "--since", since, container],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and marker in result.stdout + result.stderr:
            log("promotion READY node=%s epoch=%d" % (node, epoch))
            return
        time.sleep(1)
    raise RuntimeError("Promotion did not become READY: %s epoch %d" % (node, epoch))


def open_order_visible(token, cid):
    data = api.call("OrderSvr", "queryOpenOrder",
                    {"userid": api.USER_ID, "securityid": SYMBOL, "Location": LOCATION},
                    token, key=KEY)
    return cid in json.dumps(data)


def wait(label, condition, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise RuntimeError(label + " did not converge")


def preflight():
    if zlib.crc32(KEY.encode()) % 256 != 110:
        raise RuntimeError("Test key no longer maps to P110")
    rows = api.sql("SELECT s.location,s.market_indicator,s.security_id FROM dc_tenant_symbol s "
                   "JOIN dc_tenant t ON t.location=s.location "
                   "WHERE t.status IN ('ACTIVE','TRIAL') AND s.enabled=1")
    collisions = [row for row in rows if zlib.crc32("\x1f".join(row).encode()) % 256 == 110]
    if collisions:
        raise RuntimeError("P110 contains another active tenant symbol: %s" % collisions)
    if api.sql("SELECT status,trade_enabled FROM dc_tenant WHERE location='%s'" % LOCATION) != \
            [["SUSPENDED", "0"]]:
        raise RuntimeError("Expected isolated suspended test tenant")
    if api.sql("SELECT JSON_EXTRACT(quotas,'$.max_registered_users') FROM dc_tenant "
               "WHERE location='%s'" % LOCATION) != [["2"]]:
        raise RuntimeError("Unexpected test tenant user quota")
    if api.sql("SELECT COUNT(*) FROM dc_orders_position WHERE location='%s' "
               "AND (long_position<>0 OR short_position<>0)" % LOCATION) != [["0"]]:
        raise RuntimeError("Test tenant has non-flat position")
    if api.sql("SELECT COUNT(*) FROM dc_orders WHERE location='%s' AND "
               "ord_status IN ('New','PartiallyFilled','0','1')" % LOCATION) != [["0"]]:
        raise RuntimeError("Test tenant has pre-existing active orders")
    current, _ = assignment()
    if current.get("primary") != "OrderSvrA" or current.get("replica") != "OrderSvrB" \
            or current.get("state") != "READY":
        raise RuntimeError("Unexpected initial P110 assignment: %s" % current)
    return int(current["epoch"])


def main():
    if os.environ.get("ORDER_LIVE_ROLE_REVERSAL_CONFIRM") != LOCATION + ":" + PARTITION:
        raise RuntimeError("Explicit ORDER_LIVE_ROLE_REVERSAL_CONFIRM=EX2ENF:P110 is required")
    api.LOCATION = LOCATION
    original_epoch = preflight()
    platform = api.call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "ROLE_PLATFORM_" + RUN_ID,
        "user_id": os.environ["PLATFORM_ADMIN_USERNAME"],
        "user_name": os.environ["PLATFORM_ADMIN_USERNAME"],
        "password": os.environ["PLATFORM_ADMIN_PASSWORD"],
        "client_type": "Manager", "Location": "PLATFORM",
    })
    platform_token = platform["token"]
    api.call("ManagerSvr", "tenantApproval", {
        "action": "UPDATE_TENANT", "cid": "ROLE_ACTIVATE_" + RUN_ID,
        "request_id": "ROLE_ACTIVATE_" + RUN_ID,
        "location": LOCATION, "status": "TRIAL",
        "registration_enabled": True, "trade_enabled": True,
        "max_registered_users": 5,
    }, platform_token)
    wait("trial activation", lambda: api.sql("SELECT status,trade_enabled FROM dc_tenant "
                                              "WHERE location='%s'" % LOCATION) == [["TRIAL", "1"]])
    log("test tenant reactivated")

    username = "role" + RUN_ID.lower()
    password = secrets.token_urlsafe(24)
    registration = api.call("AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "cid": "ROLE_REGISTER_" + RUN_ID,
        "request_id": "ROLE_REGISTER_" + RUN_ID,
        "location": LOCATION, "username": username, "name": "Order Role Reversal Trader",
        "email": username + "@example.invalid", "password": password,
    })
    api.USER_ID = registration["user_id"]
    trader = api.call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "ROLE_LOGIN_" + RUN_ID,
        "user_id": username, "user_name": username, "password": password,
        "client_type": "WEB", "Location": LOCATION,
    })
    token = trader["token"]
    api.call("TradeSvr", "cashIn", {"Amount": "1000", "UserID": api.USER_ID,
                                    "Location": LOCATION, "Demo": "1"}, token, key=LOCATION)
    wait("Robot quotes", lambda: api.sql("SELECT runtime_status,open_order_count FROM dc_tenant_robot "
                                        "WHERE location='%s'" % LOCATION) == [["RUNNING", "40"]], seconds=90)
    bids, _ = api.market_book()
    price = (max(bids) - Decimal("20")).quantize(Decimal("0.1"))
    cid = "ROLE-REST-" + RUN_ID
    api.call("OrderSvr", "placeOrder", {
        "OCType": "OPEN", "OrderQty": "0.0001", "OrdType": "Limit",
        "ClOrdID": cid, "Terminal": "OrderRoleReversalE2E", "AlgoName": "cross",
        "Side": "Buy", "Price": str(price), "UserID": api.USER_ID,
        "MarketIndicator": MARKET, "TimeInForce": "GTC", "SecurityID": SYMBOL,
        "Location": LOCATION,
    }, token, key=KEY)
    wait("accepted resting order", lambda: open_order_visible(token, cid), seconds=60)
    log("resting order acknowledged and visible cid=%s" % cid)

    since = datetime.now(timezone.utc).isoformat(timespec="seconds")
    b_epoch = change_assignment(original_epoch, "OrderSvrB", "OrderSvrA")
    wait_primary("OrderSvrB", b_epoch, since)
    wait("order on promoted B", lambda: open_order_visible(token, cid), seconds=30)
    log("acknowledged order survived A-to-B role change")

    since = datetime.now(timezone.utc).isoformat(timespec="seconds")
    a_epoch = change_assignment(b_epoch, "OrderSvrA", "OrderSvrB")
    wait_primary("OrderSvrA", a_epoch, since)
    wait("order on restored A", lambda: open_order_visible(token, cid), seconds=30)
    log("acknowledged order survived B-to-A role change")

    api.call("OrderSvr", "cancelAllOrder", {
        "UserID": api.USER_ID, "SecurityID": SYMBOL, "MarketIndicator": MARKET,
        "AlgoName": "cross", "Location": LOCATION,
    }, token, key=KEY)
    wait("resting order cancel", lambda: not open_order_visible(token, cid), seconds=30)
    wait("order projection cancel", lambda: api.sql("SELECT COUNT(*) FROM dc_orders WHERE "
        "location='%s' AND user_id='%s' AND ord_status IN ('New','PartiallyFilled','0','1')" %
        (LOCATION, api.USER_ID)) == [["0"]], seconds=30)
    if api.sql("SELECT COUNT(*) FROM dc_orders_position WHERE location='%s' "
               "AND (long_position<>0 OR short_position<>0)" % LOCATION) != [["0"]]:
        raise RuntimeError("Non-flat position after role reversal")
    api.call("ManagerSvr", "tenantApproval", {
        "action": "UPDATE_TENANT", "cid": "ROLE_SUSPEND_" + RUN_ID,
        "request_id": "ROLE_SUSPEND_" + RUN_ID,
        "location": LOCATION, "status": "SUSPENDED", "max_registered_users": 2,
    }, platform_token)
    wait("tenant suspension", lambda: api.sql("SELECT status,trade_enabled FROM dc_tenant "
                                               "WHERE location='%s'" % LOCATION) == [["SUSPENDED", "0"]])
    wait("Robot stop", lambda: api.sql("SELECT runtime_status,open_order_count FROM dc_tenant_robot "
                                       "WHERE location='%s'" % LOCATION) == [["STOPPED", "0"]], seconds=60)
    log("PASS P110 %d->%d->%d, order preserved then cancelled, tenant suspended, Robot STOPPED/0" %
        (original_epoch, b_epoch, a_epoch))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FAIL: %s. Inspect P110 assignment, resting order, and tenant before any retry." % exc)
        sys.exit(1)
