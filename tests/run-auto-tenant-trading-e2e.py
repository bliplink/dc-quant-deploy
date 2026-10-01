#!/usr/bin/env python3
"""Exercise public tenant signup through auto Robot liquidity and a flat trader.

Run after exporting the local deploy env file. This uses only public/service APIs
for mutations; MySQL queries are read-only convergence checks.
"""

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from decimal import Decimal


RUN = time.strftime("%Y%m%d%H%M%S") + secrets.token_hex(2).upper()
REQUEST_ID = "TRIAL_E2E_" + RUN
EMAIL = "trial-" + RUN.lower() + "@example.invalid"
ADMIN_PASSWORD = secrets.token_urlsafe(24)
TRADER_PASSWORD = secrets.token_urlsafe(24)
TRADER = "trialtrader"
URL = "http://127.0.0.1:%s/httpapi/" % os.environ["WEB_LISTEN_PORT"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOCATION = None
USER_ID = None


def log(message):
    print("[auto-tenant-e2e] " + message, flush=True)


def sql(query):
    env = os.environ.copy()
    env["MYSQL_PWD"] = os.environ["MYSQL_PASSWORD"]
    result = subprocess.run(
        ["docker", "exec", "-i", "-e", "MYSQL_PWD=" + env["MYSQL_PWD"],
         "dc-saas-mysql", "mysql", "-u" + env["MYSQL_USERNAME"], "-N", "dc", "-e", query],
        capture_output=True, text=True, timeout=15, check=True,
    )
    return [line.split("\t") for line in result.stdout.splitlines()]


def call(server, method, content, token=None, key=None, timeout=30):
    body = {"serverName": server, "method": method, "content": content}
    if key is not None:
        body["key"] = key
    headers = {"Content-Type": "application/json"}
    if token:
        headers["sessionId"] = token
    request = urllib.request.Request(URL, json.dumps(body).encode(), headers)
    with OPENER.open(request, timeout=timeout) as response:
        result = json.load(response)
    if int(result.get("code", -1)) != 0:
        raise RuntimeError("%s.%s rejected: code=%s message=%s" %
                           (server, method, result.get("code"), result.get("message")))
    return result.get("data")


def wait(label, probe, seconds=150, interval=2):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(interval)
    raise RuntimeError("%s did not converge within %ss (last=%s)" %
                       (label, seconds, last))


def market_book():
    entries = market_entries()
    bids = [Decimal(str(x["MDEntryPx"])) for x in entries if str(x.get("MDEntryType")) == "0"]
    asks = [Decimal(str(x["MDEntryPx"])) for x in entries if str(x.get("MDEntryType")) == "1"]
    return bids, asks


def market_entries():
    data = call("MDSvr", "queryPublicMarket", {"securityID": "BTCUSDT", "location": LOCATION},
                key=LOCATION + "\x1f4\x1fBTCUSDT")
    return ((data or {}).get("orderBook") or {}).get("NoMDEntries") or []


def verify_notional_zones():
    entries = market_entries()
    report = []
    for side in ("0", "1"):
        rows = sorted((x for x in entries if str(x.get("MDEntryType")) == side),
                      key=lambda x: Decimal(str(x["MDEntryPx"])), reverse=side == "0")
        if len(rows) != 10:
            raise RuntimeError("Expected 10 Robot levels on side %s, got %s" % (side, len(rows)))
        quantities = [Decimal(str(x["MDEntrySize"])) for x in rows]
        if len(set(quantities)) < 2:
            raise RuntimeError("Robot levels have fixed quantity on side %s" % side)
        notionals = [Decimal(str(x["MDEntryPx"])) * quantity
                     for x, quantity in zip(rows, quantities)]
        total = sum(notionals)
        zone_sums = [sum(notionals[start:end]) for start, end in ((0, 3), (3, 6), (6, 10))]
        if not Decimal("300") < total < Decimal("700"):
            raise RuntimeError("Robot side %s notional is outside trial budget: %s" % (side, total))
        if any(abs(zone / total - weight) > Decimal("0.10")
               for zone, weight in zip(zone_sums, map(Decimal, ("0.3", "0.3", "0.4")))):
            raise RuntimeError("Robot side %s notional zones disagree with 3/3/4 weights: %s" %
                               (side, zone_sums))
        report.append("%s=%s (%s)" %
                      ("bid" if side == "0" else "ask", round(total, 2),
                       "/".join(str(round(value, 2)) for value in zone_sums)))
    return ", ".join(report)


def order_status(cid):
    rows = sql("SELECT ord_status,cum_qty FROM dc_orders WHERE location='%s' AND clord_id='%s' LIMIT 1" %
               (LOCATION, cid))
    return rows[0] if rows else None


def trader_position():
    rows = sql("SELECT COALESCE(long_position,0),COALESCE(short_position,0) "
               "FROM dc_orders_position WHERE location='%s' AND user_id='%s' AND security_id='BTCUSDT'" %
               (LOCATION, USER_ID))
    return tuple(map(Decimal, rows[0])) if rows else (Decimal(0), Decimal(0))


def place(token, cid, oc_type, side, price, position_side=None):
    content = {
        "OCType": oc_type, "OrderQty": "0.0001", "OrdType": "Limit",
        "ClOrdID": cid, "Terminal": "TenantAutoE2E", "AlgoName": "trial-business-check",
        "Side": side, "Price": str(price), "UserID": USER_ID,
        "MarketIndicator": "4", "TimeInForce": "IOC", "SecurityID": "BTCUSDT",
        "Location": LOCATION,
    }
    if position_side:
        content["PositionSide"] = position_side
        content["ReduceOnly"] = "true"
    try:
        call("OrderSvr", "placeOrder", content, token,
             key=LOCATION + "\x1f4\x1fBTCUSDT", timeout=30)
    except Exception:
        # Never silently repeat an ambiguous order. The ID is printed so its
        # durable/order-state outcome can be inspected before any retry.
        log("Order outcome ambiguous; inspect ClOrdID=%s before retrying." % cid)
        raise
    return wait("order " + cid,
                lambda: (s if (s := order_status(cid)) and s[0] in
                         ("Filled", "Canceled", "Cancelled", "Expired", "Rejected") else None),
                seconds=30)


def main():
    global LOCATION, USER_ID
    active = int(sql("SELECT COUNT(*) FROM dc_tenant WHERE status IN ('ACTIVE','TRIAL')")[0][0])
    if active >= 200:
        raise RuntimeError("Auto-approval safety gate reached: %s active tenants" % active)
    log("Submitting one-symbol trial application; active tenants before=%s." % active)
    submission = call("ManagerSvr", "tenantApplication", {
        "action": "SUBMIT", "cid": REQUEST_ID, "request_id": REQUEST_ID,
        "organization_name": "Trial Acceptance " + RUN,
        "contact_name": "Acceptance Trader", "contact_email": EMAIL,
        "expected_users": 2, "requested_symbols": ["BTCUSDT"],
        "requested_trial_days": 30, "admin_password": ADMIN_PASSWORD,
    })
    application_id = submission["application_id"]
    status = call("ManagerSvr", "tenantApplication", {
        "action": "STATUS", "application_id": application_id, "contact_email": EMAIL})
    if status.get("status") != "APPROVED":
        raise RuntimeError("Application not auto-approved: %s" % status.get("status"))
    LOCATION = status["approved_location"]
    log("Auto-approved location=%s application=%s." % (LOCATION, application_id))

    def bootstrap_done():
        rows = sql("SELECT status,step,COALESCE(last_error_code,''),funding_confirmed "
                   "FROM dc_tenant_liquidity_bootstrap WHERE location='%s'" % LOCATION)
        if not rows:
            return None
        state, step, error, funded = rows[0]
        if state == "BLOCKED" or state == "FAILED":
            raise RuntimeError("Bootstrap %s step=%s error=%s" % (state, step, error))
        return rows[0] if state == "COMPLETE" and funded == "1" else None

    wait("automatic liquidity bootstrap", bootstrap_done, seconds=180, interval=3)
    robots = sql("SELECT robot_id,api_user_id,enabled,runtime_status,open_order_count,"
                 "JSON_UNQUOTE(JSON_EXTRACT(strategy_config,'$.depth_quantity_mode')) "
                 "FROM dc_tenant_robot WHERE location='%s'" % LOCATION)
    if len(robots) != 1 or robots[0][2:4] != ["1", "RUNNING"] or robots[0][5] != "NOTIONAL_ZONES":
        raise RuntimeError("Default Robot not running in notional-zones mode: %s" % robots)
    def full_book():
        bids, asks = market_book()
        return (bids, asks) if len(bids) >= 10 and len(asks) >= 10 else None

    bids, asks = wait("Robot public order book", full_book, seconds=90)
    if max(bids) >= min(asks):
        raise RuntimeError("Robot book crossed")
    zone_report = verify_notional_zones()
    log("Robot=%s RUNNING, mode=NOTIONAL_ZONES, open=%s, book=%s bids/%s asks; spread=%s/%s." %
        (robots[0][0], robots[0][4], len(bids), len(asks), max(bids), min(asks)))
    log("Amount-based depth verified: %s." % zone_report)

    registration = call("AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "cid": "REGISTER_" + RUN,
        "request_id": "REGISTER_" + RUN, "location": LOCATION,
        "username": TRADER, "name": "Trial Acceptance Trader",
        "email": "trader-" + RUN.lower() + "@example.invalid",
        "password": TRADER_PASSWORD,
    })
    USER_ID = registration["user_id"]
    log("Registered trader user_id=%s." % USER_ID)
    login = call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "LOGIN_" + RUN,
        "user_id": TRADER, "user_name": TRADER, "password": TRADER_PASSWORD,
        "client_type": "WEB", "Location": LOCATION,
    })
    token = login["token"]
    call("TradeSvr", "cashIn", {"Amount": "1000", "UserID": USER_ID,
         "Location": LOCATION, "Demo": "1"}, token, key=LOCATION)
    log("Trader demo account funded with 1000 (Demo=1).")

    opening_id = "TRIAL-OPEN-" + RUN
    for attempt in range(5):
        bids, asks = market_book()
        if not asks:
            time.sleep(1)
            continue
        cid = opening_id if attempt == 0 else opening_id + "-" + str(attempt)
        state = place(token, cid, "OPEN", "Buy", min(asks))
        if state[0] == "Filled":
            opening_id = cid
            break
        if state[0] not in ("Canceled", "Cancelled", "Expired"):
            raise RuntimeError("Open order unresolved: %s %s" % (cid, state))
    else:
        raise RuntimeError("No Robot ask was filled after five IOC attempts")
    wait("long position", lambda: trader_position() if trader_position()[0] == Decimal("0.0001") else None)
    executions = sql("SELECT COUNT(*),COALESCE(SUM(last_qty),0) FROM dc_orders_execorders "
                     "WHERE location='%s' AND user_id='%s' AND order_id="
                     "(SELECT order_id FROM dc_orders WHERE location='%s' AND clord_id='%s' LIMIT 1)" %
                     (LOCATION, USER_ID, LOCATION, opening_id))
    if Decimal(executions[0][1]) != Decimal("0.0001"):
        raise RuntimeError("Opening execution projection mismatch: %s" % executions)
    log("Opening order %s filled 0.0001 BTC; execution and long position agree." % opening_id)

    closing_id = "TRIAL-CLOSE-" + RUN
    for attempt in range(5):
        bids, asks = market_book()
        if not bids:
            time.sleep(1)
            continue
        cid = closing_id if attempt == 0 else closing_id + "-" + str(attempt)
        state = place(token, cid, "ClOSE", "Sell", max(bids), "Long")
        if state[0] == "Filled":
            closing_id = cid
            break
        if state[0] not in ("Canceled", "Cancelled", "Expired"):
            raise RuntimeError("Close order unresolved: %s %s" % (cid, state))
    else:
        raise RuntimeError("No Robot bid filled the reduce-only close after five IOC attempts")
    wait("flat trader position", lambda: True if trader_position() == (Decimal(0), Decimal(0)) else None)
    active_orders = sql("SELECT COUNT(*) FROM dc_orders WHERE location='%s' AND user_id='%s' "
                        "AND ord_status IN ('New','PartiallyFilled','0','1')" % (LOCATION, USER_ID))
    if active_orders[0][0] != "0":
        raise RuntimeError("Trader still has active orders: %s" % active_orders)
    closing_exec = sql("SELECT COALESCE(SUM(last_qty),0) FROM dc_orders_execorders "
                       "WHERE location='%s' AND user_id='%s' AND order_id="
                       "(SELECT order_id FROM dc_orders WHERE location='%s' AND clord_id='%s' LIMIT 1)" %
                       (LOCATION, USER_ID, LOCATION, closing_id))
    if Decimal(closing_exec[0][0]) != Decimal("0.0001"):
        raise RuntimeError("Closing execution projection mismatch: %s" % closing_exec)

    def robot_replenished():
        rows = sql("SELECT enabled,runtime_status,open_order_count FROM dc_tenant_robot "
                   "WHERE location='%s' AND robot_id='%s'" % (LOCATION, robots[0][0]))
        bids, asks = market_book()
        return rows[0] if rows and rows[0] == ["1", "RUNNING", "20"] and len(bids) == 10 \
            and len(asks) == 10 else None

    wait("Robot replenishment after trader round trip", robot_replenished, seconds=90)
    log("PASS close=%s, position=0, trader active orders=0; Robot RUNNING with 10+10 book." %
        closing_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FAIL location=%s: %s" % (LOCATION or "not-created", exc))
        sys.exit(1)
