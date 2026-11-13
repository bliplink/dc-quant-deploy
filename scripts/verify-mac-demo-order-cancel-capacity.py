#!/usr/bin/env python3
"""Measure Demo order/cancel round trips using authenticated CUSTOM price products."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import fcntl
import json
from pathlib import Path
import runpy
import secrets
from threading import Event, Thread
import time


HERE = Path(__file__).resolve().parent
CAPACITY = runpy.run_path(str(HERE / "verify-mac-demo-robot-capacity.py"))
PRODUCT = CAPACITY["PRODUCT"]
MEASURE = CAPACITY["MEASURE"]
URL = "http://127.0.0.1:49502/httpapi/"


def api(service, method, content, token=None):
    return PRODUCT["ok"](URL, service, method, content, token)


@contextmanager
def controlled_products(run, report, password=None, admin_session=None):
    password = password or secrets.token_urlsafe(24)
    application = api("ManagerSvr", "tenantApplication", {
        "action": "SUBMIT", "cid": "CANCELCAP_" + run, "request_id": "CANCELCAP_" + run,
        "organization_name": "T554 Order Cancel Capacity " + run, "contact_name": "Demo acceptance",
        "contact_email": f"cancelcap-{run}@acceptance.invalid", "expected_users": 32,
        "admin_password": password,
    })
    if application.get("status") != "APPROVED":
        raise RuntimeError("The controlled-price Demo tenant was not approved")
    location = application["approved_location"]
    admin = api("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "CANCELCAP_" + run, "user_id": "tenantadmin",
        "user_name": "tenantadmin", "password": password, "client_type": "TenantAdmin",
        "Location": location,
    })["token"]
    if admin_session is not None:
        admin_session["token"] = admin
    report["controlled_robot_stop"] = stop_trial_robot_after_bootstrap(location, admin)
    source = "QA_CANCEL_" + run.upper()
    api("AdminSvr", "tenantDataSourceAdmin", {
        "action": "CREATE", "location": location, "cid": source, "data_source_id": source,
        "source_name": "Order cancel acceptance price", "source_type": "CUSTOM",
        "source_symbol": "BTC_CANCEL",
    }, admin)
    products = (("ORDER_ONLY", "BTC003USDT"), ("TRADE", "BTC004USDT"))
    for mode, symbol in products:
        api("AdminSvr", "tenantProductDataSource", {
            "action": "CREATE", "location": location, "cid": source + symbol,
            "security_id": symbol, "product_name": "Cancel capacity " + mode,
            "data_source_id": source, "template_security_id": "BTCUSDT", "matching_mode": mode,
        }, admin)
    broker = api("LoginSvr", "tenantApiKeyAdmin", {
        "action": "CREATE", "type": "broker", "label": "cancel-capacity-" + run,
        "permissions": "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE", "cid": source,
    }, admin)
    done = Event()
    publisher = None
    price = {"location": location, "source": source, "kind": "Authenticated Demo CUSTOM price",
             "index_price": "90000", "mark_price": "90001", "interval_seconds": 1,
             "published": 0, "errors": []}
    report["price_source"] = price
    try:
        for attempt in range(20):
            try:
                session = PRODUCT["signed_login"](URL, broker["api_key"], broker["secret_key"], location)["token"]
                break
            except RuntimeError as exc:
                if not any(code in str(exc) for code in ("code=7000", "code=7004")) or attempt == 19:
                    raise
                time.sleep(3)

        def publish():
            api("APSSvr", "publishBrokerPrice", {
                "location": location, "data_source_id": source, "market_indicator": "4",
                "index_price": "90000", "mark_price": "90001", "source_time_ms": int(time.time() * 1000),
                "ttl_ms": 60000, "config_version": 1, "sequence": price["published"] + 1,
                "cid": source + str(price["published"] + 1),
            }, session)
            price["published"] += 1

        def maintain():
            while not done.wait(1):
                try:
                    publish()
                except Exception as exc:
                    price["errors"].append({"at": datetime.now(timezone.utc).isoformat(),
                                            "failure": type(exc).__name__})
                    return

        publish()
        publisher = Thread(target=maintain, name="demo-cancel-price-publisher")
        publisher.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                markets = [api("MDSvr", "queryPublicMarket", {"location": location, "securityID": symbol})
                           for _, symbol in products]
            except RuntimeError as unavailable:
                if "code=5004" not in str(unavailable):
                    raise
                time.sleep(1)
                continue
            if all(market.get("ticker", {}).get("MarkPrice") == "90001" for market in markets):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Authenticated custom prices did not reach both products")
        yield location, products
        if price["errors"]:
            raise RuntimeError("Controlled price publication failed during measurement")
    finally:
        done.set()
        if publisher is not None:
            publisher.join()
        deleted = PRODUCT["call"](URL, "LoginSvr", "tenantApiKeyAdmin", {
            "action": "DELETE", "api_key": broker["api_key"], "cid": "CANCELCAP_DELETE_" + run,
        }, admin)
        price["broker_key_deleted"] = deleted.get("code") == 0


def balances(location, user):
    return PRODUCT["readonly_sql"](
        "SELECT balance,used_margin,freezed_margin,freezed_commission FROM dc_users_balance "
        f"WHERE location='{location}' AND user_id='{user}' ORDER BY currency")


def stop_trial_robot_after_bootstrap(location, token):
    # The bootstrap inserts a disabled Robot before its later ENABLE phase.
    # A STOP during that gap is a no-op and would be overwritten by ENABLE.
    deadline = time.monotonic() + 180
    while PRODUCT["readonly_sql"](
            "SELECT status FROM dc_tenant_liquidity_bootstrap "
            f"WHERE location='{location}'") != [["COMPLETE"]]:
        if time.monotonic() >= deadline:
            raise RuntimeError("Controlled tenant liquidity bootstrap did not complete")
        time.sleep(.5)
    api("ManagerSvr", "robotControl", {
        "action": "STOP", "location": location, "robot_id": "trial-liquidity-BTCUSDT",
        "request_id": "T554_CONTROLLED_STOP_" + location,
        "cid": "T554_CONTROLLED_STOP_" + location,
    }, token)
    deadline = time.monotonic() + 180
    while PRODUCT["readonly_sql"](
            "SELECT enabled,COALESCE(runtime_owner,'') FROM dc_tenant_robot "
            f"WHERE location='{location}' AND robot_id='trial-liquidity-BTCUSDT'") != [["0", ""]]:
        if time.monotonic() >= deadline:
            raise RuntimeError("Controlled tenant Robot did not release its runtime owner")
        time.sleep(.5)
    return {"bootstrap_complete_before_stop": True, "disabled_and_owner_released": True}


def open_orders(trader, symbol):
    location, user, token = trader
    return api("OrderSvr", "queryOpenOrder", {
        "location": location, "securityid": symbol, "SecurityID": symbol,
        "marketIndicator": "4", "userid": user, "maxOrderCount": 100,
    }, token)


def own_order(rows, client):
    return [row for row in rows
            if (row.get("ClOrdID") or row.get("ClOrderID") or row.get("clOrdID")) == client]


def await_order(trader, symbol, client, present):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        rows = own_order(open_orders(trader, symbol), client)
        if not present and not rows:
            return None
        if present and len(rows) == 1 and rows[0].get("OrdStatus") == "New":
            return rows[0]["OrderID"]
        time.sleep(0.05)
    raise RuntimeError("Resting order state did not converge")


def new_trader(location, symbol, mode, run, index, password=None, funding_amount=Decimal("10000")):
    funding_amount = Decimal(str(funding_amount))
    if not funding_amount.is_finite() or not 0 < funding_amount <= 100000:
        raise ValueError("Benchmark funding must be positive and at most 100000")
    username = f"cancelcap_{run}_{index}"
    password = password or secrets.token_urlsafe(24)
    user = str(api("AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "location": location, "username": username,
        "name": "T554 cancel capacity", "email": username + "@acceptance.invalid",
        "password": password, "request_id": username, "cid": username,
    })["user_id"])
    token = api("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": username, "user_id": user, "user_name": username,
        "password": password, "client_type": "WEB", "Location": location,
    })["token"]
    if mode == "TRADE":
        api("TradeSvr", "setLeverage", {
            "userID": user, "securityID": symbol, "location": location, "leverage": 10,
        }, token)
        api("TradeSvr", "cashIn", {
            "Amount": str(funding_amount), "UserID": user, "Location": location,
            "Demo": "0", "Info1": username,
        }, token)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            rows = balances(location, user)
            if len(rows) == 1 and Decimal(rows[0][0]) == funding_amount:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Funded account did not converge")
    return location, user, token


def cancel(trader, symbol, record):
    location, user, token = trader
    return api("OrderSvr", "cancelOrder", {
        "UserID": user, "SecurityID": symbol, "MarketIndicator": "4",
        "OrderID": record.get("order_id", ""), "ClOrdID": record["client_order_id"],
        "AlgoName": "cross", "Location": location,
    }, token)


def worker(trader, symbol, price, prefix, index, deadline, stop):
    location, user, token = trader
    records = []
    while time.monotonic() < deadline and not stop.is_set():
        record = {"client_order_id": f"{prefix}-{index}-{len(records)}",
                  "location": location, "user_id": user, "passed": False}
        records.append(record)
        try:
            begun = time.monotonic()
            api("OrderSvr", "placeOrder", {
                "OCType": "OPEN", "OrderQty": "0.001", "OrdType": "Limit",
                "ClOrdID": record["client_order_id"], "Terminal": "API", "AlgoName": "cross",
                "Side": "Buy", "Price": price, "UserID": user, "MarketIndicator": "4",
                "TimeInForce": "GTC", "SecurityID": symbol, "ReduceOnly": "false",
                "Demo": "0", "Location": location,
            }, token)
            record["place_ack_ms"] = round((time.monotonic() - begun) * 1000, 3)
            record["order_id"] = await_order(trader, symbol, record["client_order_id"], True)
            record["place_new_ms"] = round((time.monotonic() - begun) * 1000, 3)
            cancel_started = time.monotonic()
            cancel(trader, symbol, record)
            record["cancel_ack_ms"] = round((time.monotonic() - cancel_started) * 1000, 3)
            await_order(trader, symbol, record["client_order_id"], False)
            record["cancel_absent_ms"] = round((time.monotonic() - cancel_started) * 1000, 3)
            record["cycle_ms"] = round((time.monotonic() - begun) * 1000, 3)
            record["passed"] = True
        except Exception as exc:
            record["failure"] = type(exc).__name__
            stop.set()
            try:
                cancel(trader, symbol, record)
                await_order(trader, symbol, record["client_order_id"], False)
                record["cleanup_confirmed"] = True
            except Exception as cleanup:
                record["cleanup_failure"] = type(cleanup).__name__
    return records


def distribution(records, key):
    values = sorted(record[key] for record in records if key in record)
    return {"samples": len(values), "p50": MEASURE["percentile"](values, 0.5),
            "p95": MEASURE["percentile"](values, 0.95), "p99": MEASURE["percentile"](values, 0.99),
            "p99_9": MEASURE["percentile"](values, 0.999)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--mode", choices=("ORDER_ONLY", "TRADE"))
    parser.add_argument("--concurrency", choices=(1, 4, 8), type=int)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 300:
        parser.error("Use a 30 to 300 second window per concurrency level")
    root = args.generation.resolve(strict=True)
    run = secrets.token_hex(4)
    report = {"generation": root.name, "common_release": CAPACITY["common_release_identity"](root),
              "run": run, "passed": False, "phases": [],
              "requested_mode": args.mode, "requested_concurrency": args.concurrency,
              "scope": "Closed-loop place/New/cancel/absent via HTTP, with live Robots in background",
              "latency_measurement": {
                  "place_ack_ms": "Request to HTTP success response",
                  "place_new_ms": "Request to New observed through authenticated order query",
                  "cancel_ack_ms": "Cancel request to HTTP success response",
                  "cancel_absent_ms": "Cancel request to absence observed through authenticated open-order query",
                  "state_query_retry_seconds": 0.05,
              }}
    output = root / f"order-cancel-capacity-{run}.json"
    with (root.parent / ".mac-demo-fresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        CAPACITY["require_strict_demo"](root)
        try:
            with controlled_products(run, report) as (location, products):
                report["background_robots_at_admission"] = CAPACITY["demo_tenants"]()
                for mode, symbol in products:
                    if args.mode is not None and mode != args.mode:
                        continue
                    actual = PRODUCT["readonly_sql"](
                        f"SELECT matching_mode FROM dc_tenant_symbol WHERE location='{location}' AND security_id='{symbol}'")
                    if actual != [[mode]]:
                        raise RuntimeError("Actual product mode differs from the controlled test")
                    traders = [new_trader(location, symbol, mode, run, mode.lower() + str(i)) for i in range(8)]
                    before = {user: balances(loc, user) for loc, user, _ in traders}
                    for concurrency in ((args.concurrency,) if args.concurrency is not None else (1, 4, 8)):
                        control_before = CAPACITY["require_strict_demo"](root)
                        market = api("MDSvr", "queryPublicMarket", {"location": location, "securityID": symbol})
                        bids = [Decimal(row["MDEntryPx"]) for row in market["orderBook"]["NoMDEntries"]
                                if row["MDEntryType"] == "0"]
                        trades = [Decimal(row["MDEntryPx"])
                                  for row in market.get("recentTrades", {}).get("NoMDEntries", [])]
                        if bids:
                            reference = max(bids)
                        elif trades:
                            reference = max(trades)
                        else:
                            reference = Decimal(market["ticker"]["MarkPrice"])
                        price = str((reference / 2).quantize(Decimal("1"), rounding=ROUND_DOWN))
                        phase = {"mode": mode, "symbol": symbol, "location": location,
                                 "concurrency": concurrency, "price": price,
                                 "started_at": datetime.now(timezone.utc).isoformat()}
                        report["phases"].append(phase)
                        prefix = f"T554CC-{run}-{mode}-{concurrency}"
                        begun = time.monotonic()
                        deadline = begun + args.seconds
                        stop = Event()
                        with MEASURE["sample_resources"](root.name) as resources, \
                                ThreadPoolExecutor(max_workers=concurrency) as clients:
                            tasks = [clients.submit(worker, trader, symbol, price, prefix, i, deadline, stop)
                                     for i, trader in enumerate(traders[:concurrency])]
                            records = [record for task in tasks for record in task.result()]
                        elapsed = time.monotonic() - begun
                        control_after = CAPACITY["require_strict_demo"](root)
                        phase.update(elapsed_seconds=round(elapsed, 3), records=records, resources=resources,
                                     control_generation_before=control_before, control_generation_after=control_after,
                                     complete_cycles_per_second=round(sum(r["passed"] for r in records) / elapsed, 3),
                                     place_ack_ms=distribution(records, "place_ack_ms"),
                                     place_new_ms=distribution(records, "place_new_ms"),
                                     cancel_ack_ms=distribution(records, "cancel_ack_ms"),
                                     cancel_absent_ms=distribution(records, "cancel_absent_ms"),
                                     cycle_ms=distribution(records, "cycle_ms"))
                        # An asynchronous maker publication can follow an earlier
                        # absent query. Recheck after the clients have drained.
                        time.sleep(3)
                        sql_deadline = time.monotonic() + 90
                        while time.monotonic() < sql_deadline:
                            rows = PRODUCT["readonly_sql"](
                                "SELECT o.clord_id,o.order_id,o.ord_status,COUNT(e.exec_id) FROM dc_orders o "
                                "LEFT JOIN dc_orders_execorders e ON e.location=o.location "
                                "AND e.user_id=o.user_id AND e.order_id=o.order_id "
                                f"WHERE o.location='{location}' AND o.clord_id LIKE '{prefix}-%' "
                                "GROUP BY o.clord_id,o.order_id,o.ord_status")
                            actual = {row[0] for row in rows}
                            expected = {record["client_order_id"] for record in records}
                            funds = {user: balances(loc, user) for loc, user, _ in traders}
                            remaining = [row for trader in traders for row in open_orders(trader, symbol)]
                            phase["passed"] = (bool(records) and all(r["passed"] for r in records)
                                               and control_before == control_after
                                               and actual == expected and len(rows) == len(expected)
                                               and all(row[2] in ("Cancelled", "Canceled") and row[3] == "0"
                                                       for row in rows) and funds == before and not remaining)
                            if phase["passed"] or stop.is_set():
                                break
                            time.sleep(1)
                        phase.update(sql_orders=rows, balances_before=before, balances_after=funds,
                                     remaining_open_order_ids=[row.get("OrderID") for row in remaining])
                        output.write_text(json.dumps(report, indent=2) + "\n")
                        print(json.dumps({key: value for key, value in phase.items()
                                          if key not in ("records", "resources", "sql_orders",
                                                         "balances_before", "balances_after")}), flush=True)
                        if not phase["passed"]:
                            cleanup = []
                            for trader in traders:
                                for row in open_orders(trader, symbol):
                                    client = row.get("ClOrdID") or row.get("ClOrderID")
                                    if not client or not client.startswith(f"T554CC-{run}-"):
                                        raise RuntimeError("Unexpected order in an isolated test account")
                                    record = {"client_order_id": client, "order_id": row["OrderID"]}
                                    try:
                                        cancel(trader, symbol, record)
                                        await_order(trader, symbol, client, False)
                                        record["cleanup_confirmed"] = True
                                    except Exception as exc:
                                        record["cleanup_failure"] = type(exc).__name__
                                    cleanup.append(record)
                            phase["failure_cleanup"] = cleanup
                            raise RuntimeError("Order/cancel phase did not reconcile")
            CAPACITY["require_strict_demo"](root)
            report["passed"] = True
        except Exception as exc:
            report["failure"] = type(exc).__name__ + ": " + str(exc)[:180]
        finally:
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            output.write_text(json.dumps(report, indent=2) + "\n")
    print(("PASS " if report["passed"] else "NO_GO ") + str(output), flush=True)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
