#!/usr/bin/env python3
"""Measure Demo Robot book replenishment after API-only multi-level trades.

Export a protected local deploy env first, then run with --location LOCATION.
The target must be an isolated trial with one running Robot and no user
positions. Business mutations use public/service APIs; SQL is read-only.
"""

import argparse
from datetime import datetime
import importlib.util
import json
import os
import secrets
import sys
import time
from decimal import Decimal
from pathlib import Path


base = Path(__file__).with_name("run-auto-tenant-trading-e2e.py")
spec = importlib.util.spec_from_file_location("tenant_e2e", base)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
ACTIVE_TOKEN = None
ACTIVE_RUN_ID = None


def depth():
    started_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
    started = time.monotonic()
    entries = api.market_entries()
    elapsed_ms = (time.monotonic() - started) * 1000
    if elapsed_ms >= 500:
        print("[robot-replenish] SLOW_DEPTH location=%s started_at=%s finished_at=%s duration_ms=%.1f" %
              (api.LOCATION, started_at, datetime.now().astimezone().isoformat(timespec="milliseconds"),
               elapsed_ms), flush=True)
    book = {}
    for side in ("0", "1"):
        rows = [(Decimal(str(x["MDEntryPx"])), Decimal(str(x["MDEntrySize"])))
                for x in entries if str(x.get("MDEntryType")) == side]
        book[side] = sorted(rows, reverse=side == "0")
    return book


def is_full(book, baseline, expected_levels):
    for side in ("0", "1"):
        rows = book[side]
        if len(rows) != expected_levels:
            return False
        notional = sum(price * quantity for price, quantity in rows)
        if not baseline[side] * Decimal("0.95") <= notional <= baseline[side] * Decimal("1.05"):
            return False
    return True


def notional(book):
    return {side: sum(price * quantity for price, quantity in book[side])
            for side in ("0", "1")}


def place(token, cid, side, quantity, price, close=False):
    content = {
        "OCType": "CLOSE" if close else "OPEN", "OrderQty": str(quantity),
        "OrdType": "Limit", "ClOrdID": cid, "Terminal": "RobotReplenishE2E",
        "AlgoName": "depth-hit", "Side": side, "Price": str(price),
        "UserID": api.USER_ID, "MarketIndicator": "4", "TimeInForce": "IOC",
        "SecurityID": "BTCUSDT", "Location": api.LOCATION,
    }
    if close:
        content.update({"PositionSide": "Long", "ReduceOnly": "true"})
    started_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
    started = time.monotonic()
    try:
        api.call("OrderSvr", "placeOrder", content, token,
                 key=api.LOCATION + "\x1f4\x1fBTCUSDT", timeout=10)
    except Exception:
        # A timed-out request may still commit. Never re-use or automatically
        # retry its ClOrdID; the operator must inspect the order state first.
        raise RuntimeError("Ambiguous placeOrder outcome for %s; inspect before retry" % cid)
    elapsed_ms = (time.monotonic() - started) * 1000
    if elapsed_ms >= 500:
        finished_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        print("[robot-replenish] SLOW_PLACE cid=%s side=%s close=%s started_at=%s "
              "finished_at=%s duration_ms=%.1f" %
              (cid, side, close, started_at, finished_at, elapsed_ms), flush=True)
    return elapsed_ms


def filled_quantity(cid):
    rows = api.sql("SELECT ord_status,COALESCE(cum_qty,0) FROM dc_orders "
                   "WHERE location='%s' AND clord_id='%s' LIMIT 1" % (api.LOCATION, cid))
    if rows and rows[0][0] in ("Filled", "Canceled", "Cancelled", "Expired", "Rejected"):
        return Decimal(rows[0][1])
    return None


def wait_fill(cid):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        quantity = filled_quantity(cid)
        if quantity is not None:
            return quantity
        time.sleep(0.1)
    raise RuntimeError("Order projection missing for %s" % cid)


def observe_replenishment(baseline, started, expected_levels):
    # With deeper resting liquidity, the public top ten can stay complete
    # throughout a fill. In that case first_full_ms is only sampling latency,
    # not a claim that the internal 40-order target was replenished that fast.
    samples = 0
    minimum = {"0": expected_levels, "1": expected_levels}
    gap_seen = False
    first_full_ms = None
    last_recovered_ms = None
    first_recovered_ms = None
    gap_started_ms = None
    longest_gap_ms = 0
    gap_events = 0
    last_full = True  # The pre-order book passed the full-book gate.
    # Continue for a fixed window: an asynchronous match can arrive after the
    # first apparently full snapshot, so stopping at that snapshot is unsafe.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        book = depth()
        samples += 1
        minimum = {side: min(minimum[side], len(book[side])) for side in minimum}
        full = is_full(book, baseline, expected_levels)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        if not full:
            gap_seen = True
            if gap_started_ms is None:
                gap_started_ms = elapsed_ms
                gap_events += 1
        elif first_full_ms is None:
            first_full_ms = elapsed_ms
        if full and gap_started_ms is not None:
            longest_gap_ms = max(longest_gap_ms, elapsed_ms - gap_started_ms)
            gap_started_ms = None
            if first_recovered_ms is None:
                first_recovered_ms = elapsed_ms
            last_recovered_ms = elapsed_ms
        last_full = full
        time.sleep(0.1)
    if not last_full:
        raise RuntimeError("Robot book did not replenish within 5 s; min levels=%s" % minimum)
    return (first_recovered_ms or first_full_ms, last_recovered_ms or first_full_ms,
            round(longest_gap_ms, 1), gap_events, gap_seen, minimum, samples)


def percentile(values, percent):
    ordered = sorted(values)
    point = (len(ordered) - 1) * percent / 100
    lower = int(point)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (point - lower), 1)


def close_position(token, run_id, cycle, latencies):
    for attempt in range(8):
        remaining = api.trader_position()[0]
        if remaining == 0:
            return
        book = depth()
        if not book["0"]:
            time.sleep(0.2)
            continue
        cid = "RPL-%s-C%d-%d" % (run_id, cycle, attempt)
        # Cross all currently visible bids; IOC prevents a stranded close order.
        price = book["0"][-1][0] - Decimal("50")
        latencies.append(place(token, cid, "Sell", remaining, price, close=True))
        filled = wait_fill(cid)
        if filled == 0:
            continue
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and api.trader_position()[0] == remaining:
            time.sleep(0.1)
        if api.trader_position()[0] == remaining:
            raise RuntimeError("Close execution did not reach position projection: %s" % cid)
    api.wait("flat position", lambda: True if api.trader_position() ==
             (Decimal(0), Decimal(0)) else None, seconds=15, interval=0.2)


def run(location, cycles, levels, target_levels, visible_levels):
    global ACTIVE_TOKEN, ACTIVE_RUN_ID
    api.LOCATION = location
    rows = api.sql("SELECT status,trade_enabled FROM dc_tenant WHERE location='%s'" % location)
    if rows != [["TRIAL", "1"]]:
        raise RuntimeError("Target must be an active trial tenant: %s" % rows)
    robots = api.sql("SELECT enabled,runtime_status,open_order_count FROM dc_tenant_robot "
                     "WHERE location='%s'" % location)
    if robots != [["1", "RUNNING", str(target_levels * 2)]]:
        raise RuntimeError("Target must have one running %d-order Robot: %s" %
                           (target_levels * 2, robots))
    nonflat = api.sql("SELECT COUNT(*) FROM dc_orders_position WHERE location='%s' "
                      "AND (long_position<>0 OR short_position<>0)" % location)
    if nonflat[0][0] != "0":
        raise RuntimeError("Tenant has pre-existing positions")
    baseline_book = depth()
    if len(baseline_book["0"]) != visible_levels or len(baseline_book["1"]) != visible_levels:
        raise RuntimeError("Robot did not start with %d+%d visible levels" %
                           (visible_levels, visible_levels))

    run_id = time.strftime("%H%M%S") + secrets.token_hex(2).upper()
    username = "repl" + run_id.lower()
    password = secrets.token_urlsafe(24)
    registration = api.call("AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "cid": "RPL_REG_" + run_id,
        "request_id": "RPL_REG_" + run_id, "location": location,
        "username": username, "name": "Robot Replenishment Trader",
        "email": username + "@example.invalid", "password": password,
    })
    api.USER_ID = registration["user_id"]
    login = api.call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "RPL_LOGIN_" + run_id,
        "user_id": username, "user_name": username, "password": password,
        "client_type": "WEB", "Location": location,
    })
    token = login["token"]
    ACTIVE_TOKEN = token
    ACTIVE_RUN_ID = run_id
    api.call("TradeSvr", "cashIn", {"Amount": "10000", "UserID": api.USER_ID,
             "Location": location, "Demo": "1"}, token, key=location)
    print("[robot-replenish] location=%s user_id=%s cycles=%s hit_levels=%s target_levels=%s visible_levels=%s" %
          (location, api.USER_ID, cycles, levels, target_levels, visible_levels), flush=True)

    order_ms = []
    visible_full_ms = []
    longest_gaps_ms = []
    gaps = 0
    extra_gap_events = 0
    for cycle in range(cycles):
        book = api.wait("full starting book", lambda: (b if is_full(b := depth(),
                           notional(baseline_book), visible_levels) else None),
                        seconds=30, interval=0.2)
        budget = notional(book)
        asks = book["1"][:levels]
        quantity = sum(size for _, size in asks)
        cid = "RPL-%s-O%d" % (run_id, cycle)
        started = time.monotonic()
        order_ms.append(place(token, cid, "Buy", quantity,
                              asks[-1][0] + Decimal("50")))
        # Sample immediately after the API response; waiting for the MySQL
        # projection first can hide a short real book gap.
        recovery, last_recovery, longest_gap, gap_events, gap_seen, minimum, samples = \
            observe_replenishment(budget, started, visible_levels)
        filled = wait_fill(cid)
        if filled <= 0:
            raise RuntimeError("No ask fill for %s" % cid)
        api.wait("opening position", lambda: api.trader_position()[0] if
                 api.trader_position()[0] >= filled else None, seconds=15, interval=0.1)
        visible_full_ms.append(recovery)
        longest_gaps_ms.append(longest_gap)
        gaps += int(gap_seen)
        extra_gap_events += max(0, gap_events - 1)
        print("[robot-replenish] cycle=%d filled=%s place_ms=%.1f visible_full_ms=%.1f "
              "last_recovery_ms=%.1f longest_gap_ms=%.1f gap_events=%d min_levels=%s samples=%d" %
              (cycle + 1, filled, order_ms[-1], recovery, last_recovery, longest_gap,
               gap_events, minimum, samples), flush=True)
        close_position(token, run_id, cycle, order_ms)
        api.wait("flat position", lambda: True if api.trader_position() ==
                 (Decimal(0), Decimal(0)) else None, seconds=15, interval=0.2)
        robot_state = api.sql("SELECT enabled,runtime_status,open_order_count FROM dc_tenant_robot "
                              "WHERE location='%s'" % location)
        if robot_state != [["1", "RUNNING", str(target_levels * 2)]]:
            raise RuntimeError("Robot target not restored after cycle %d: %s" %
                               (cycle + 1, robot_state))

    api.wait("full final book", lambda: True if is_full(depth(),
             notional(baseline_book), visible_levels) else None, seconds=30, interval=0.2)
    active = api.sql("SELECT COUNT(*) FROM dc_orders WHERE location='%s' AND user_id='%s' "
                     "AND ord_status IN ('New','PartiallyFilled','0','1')" %
                     (location, api.USER_ID))
    if active[0][0] != "0":
        raise RuntimeError("Trader active orders remain: %s" % active)
    report = {"location": location, "cycles": cycles, "levels_hit": levels,
              "target_levels_per_side": target_levels,
              "visible_levels_per_side": visible_levels,
              "visible_target_deviation_cycles": gaps,
              "extra_gap_events": extra_gap_events,
              "visible_full_ms_p50": percentile(visible_full_ms, 50),
              "visible_full_ms_p95": percentile(visible_full_ms, 95),
              "visible_full_ms_p99": percentile(visible_full_ms, 99),
              "visible_full_ms_max": round(max(visible_full_ms), 1),
              "longest_gap_ms_max": round(max(longest_gaps_ms), 1),
              "place_ms_p50": percentile(order_ms, 50),
              "place_ms_p95": percentile(order_ms, 95),
              "place_ms_p99": percentile(order_ms, 99),
              "place_ms_max": round(max(order_ms), 1),
              "final_position": "0", "active_orders": 0}
    print("[robot-replenish] PASS " + json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", required=True)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--target-levels", type=int, default=20)
    parser.add_argument("--visible-levels", type=int, default=10)
    args = parser.parse_args()
    if not (args.location.isalnum() and len(args.location) == 6 and args.location.isupper()):
        parser.error("location must be six uppercase letters/digits")
    if not 1 <= args.cycles <= 50 or not 1 <= args.levels <= args.visible_levels <= args.target_levels <= 50:
        parser.error("cycles must be 1-50 and hit <= visible <= target levels (max 50)")
    try:
        run(args.location, args.cycles, args.levels, args.target_levels, args.visible_levels)
    except Exception as exc:
        print("[robot-replenish] FAIL: %s" % exc, file=sys.stderr, flush=True)
        if ACTIVE_TOKEN and api.USER_ID and api.LOCATION:
            try:
                # Settle an acknowledged IOC before cleanup. A truly
                # ambiguous timeout still requires operator inspection.
                for _ in range(30):
                    if api.trader_position()[0] > 0:
                        break
                    time.sleep(0.1)
                if api.trader_position()[0] > 0:
                    close_position(ACTIVE_TOKEN, ACTIVE_RUN_ID, 99, [])
                    print("[robot-replenish] CLEANUP: confirmed long position closed via Reduce-Only API",
                          file=sys.stderr, flush=True)
            except Exception as cleanup_error:
                print("[robot-replenish] CLEANUP FAILED: %s" % cleanup_error,
                      file=sys.stderr, flush=True)
        sys.exit(1)
