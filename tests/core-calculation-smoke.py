#!/usr/bin/env python3
"""Small local API regression. SQL is SELECT-only; no restart or fixture reset.

Use a quiet existing *_E2E tenant. Accounts are newly registered, never reused.
Mutations are never retried after an ambiguous response. A failed run preserves
positions and evidence; only its fresh accounts' resting orders are cancelled.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import time
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


D = Decimal
SCALE = D("0.00000001")


def money(value):
    return D(value).quantize(SCALE, rounding=ROUND_HALF_UP)


def expected_margin(qty, price, leverage, rate, side):
    bankruptcy = price * (leverage + (1 if side == "Short" else -1)) / leverage
    return money(qty * price / leverage) + money(qty * bankruptcy * rate)


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError("Unsupported identifier")
    return value


class Smoke:
    def __init__(self, location, base_url, run_id):
        self.location = identifier(location)
        if not re.search(r"(^|_)E2E($|_)", location):
            raise ValueError("A dedicated E2E tenant is required")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("This runner is restricted to the local simulated stack")
        self.endpoint = base_url.rstrip("/") + "/httpapi/"
        self.run_id = identifier(run_id)
        self.sessions = {}
        self.accounts = []
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.report = {"runId": run_id, "location": location, "passed": False,
                       "checks": [], "accounts": self.accounts,
                       "scope": "small synthetic linear BTCUSDT test; not full acceptance"}

    def sql(self, query):
        if not query.lstrip().upper().startswith("SELECT ") or ";" in query:
            raise ValueError("SQL observer accepts a single SELECT only")
        env = dict(os.environ, MYSQL_PWD=os.environ["MYSQL_PASSWORD"])
        result = subprocess.run(
            ["docker", "exec", "-i", "-e", "MYSQL_PWD", "dc-saas-mysql", "mysql",
             "-u" + os.environ["MYSQL_USERNAME"], "-N", "-B", "dc", "-e", query],
            env=env, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError("SQL observer failed (details withheld)")
        return [line.split("\t") for line in result.stdout.splitlines()]

    def api(self, server, method, content, user=None):
        key = self.location
        if server == "OrderSvr":
            key += "\x1f4\x1fBTCUSDT"
        request = urllib.request.Request(self.endpoint, data=json.dumps({
            "serverName": server, "method": method, "key": key,
            "content": content}).encode(), headers={"Content-Type": "application/json"})
        if user:
            request.add_header("sessionId", self.sessions[user])
        try:
            with self.opener.open(request, timeout=30) as response:
                value = json.load(response, parse_float=Decimal)
        except Exception:
            # Never include request/response bodies, session IDs or passwords.
            raise RuntimeError(server + "/" + method + " transport/JSON failure; not retried") from None
        if value.get("code") != 0:
            raise RuntimeError(server + "/" + method + " rejected, code=" + str(value.get("code")))
        return value

    def record(self, name, details):
        self.report["checks"].append({"name": name, "details": details})
        print("[calculation-smoke] PASS " + name, flush=True)

    def equal(self, name, actual, expected):
        if D(str(actual)) != D(str(expected)):
            raise AssertionError(name + ": actual=" + str(actual) + " expected=" + str(expected))

    def wait(self, probe, predicate, name):
        deadline = time.monotonic() + 60
        while True:
            value = probe()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise AssertionError(name + " did not converge within 60 seconds")
            time.sleep(1)

    def preflight(self):
        rows = self.sql("SELECT status,registration_enabled,trade_enabled FROM dc_tenant "
                        "WHERE location='" + self.location + "'")
        if len(rows) != 1 or rows[0][0] not in ("ACTIVE", "TRIAL") or rows[0][1:] != ["1", "1"]:
            raise AssertionError("Tenant must already exist and allow registration/trading")
        active = self.sql("SELECT COUNT(*) FROM dc_orders WHERE location='" + self.location +
                          "' AND ord_status IN ('New','Partially_Filled')")[0][0]
        robots = self.sql("SELECT COUNT(*) FROM dc_tenant_robot WHERE location='" + self.location +
                          "' AND enabled=1")[0][0]
        if active != "0" or robots != "0":
            raise AssertionError("Tenant contains active orders or enabled robots; refusing writes")
        market = self.api("MDSvr", "queryPublicMarket", {
            "location": self.location, "securityID": "BTCUSDT"})["data"]
        book = market["orderBook"]
        if book.get("Location") != self.location or book.get("NoMDEntries") != []:
            raise AssertionError("Runtime order book is not an empty tenant-scoped baseline")
        mark = D(market["ticker"]["MarkPrice"])
        if not D("75000") < mark < D("95000"):
            raise AssertionError("Fixed test prices require a mark price between 75000 and 95000")
        self.record("quiet tenant and live empty book", {"markPrice": str(mark)})

    def register(self, role):
        username = identifier("calc_" + self.run_id + "_" + role)
        if self.sql("SELECT COUNT(*) FROM dc_users WHERE user_name='" + username + "'")[0][0] != "0":
            raise AssertionError("Never reuse calculation accounts")
        password = secrets.token_urlsafe(24)
        result = self.api("AdminSvr", "tenantUserRegistration", {
            "action": "REGISTER", "location": self.location, "username": username,
            "name": "Calculation " + role, "email": username + "@example.invalid",
            "password": password, "request_id": username, "cid": username})
        user = identifier(result["data"]["user_id"])
        self.accounts.append({"role": role, "userId": user, "username": username})
        result = self.api("LoginSvr", "SYS.ATS.LOGIN", {
            "user_id": user, "user_name": username, "password": password, "method": "login",
            "client_type": "WEB", "cid": username, "Location": self.location})
        self.sessions[user] = result["data"]["token"]
        return user

    def balance(self, user):
        return self.api("TradeSvr", "queryAccountBalance", {}, user)["data"]

    def position(self, user):
        return self.api("TradeSvr", "queryTradePosition", {"securityid": "BTCUSDT"}, user)["data"]

    def order(self, user, side, qty, price, suffix, close_side=None):
        content = {"OCType": "ClOSE" if close_side else "OPEN", "OrderQty": str(qty),
                   "OrdType": "Limit", "ClOrdID": "CALC-" + self.run_id + "-" + suffix,
                   "Terminal": "API", "AlgoName": "cross", "Side": side,
                   "Price": str(price), "UserID": user, "MarketIndicator": "4",
                   "TimeInForce": "GTC", "SecurityID": "BTCUSDT",
                   "ReduceOnly": "true" if close_side else "false", "Demo": "0",
                   "Location": self.location}
        if close_side:
            content["PositionSide"] = close_side
        self.api("OrderSvr", "placeOrder", content, user)
        return content["ClOrdID"]

    def order_status(self, clid, expected):
        self.wait(lambda: self.sql("SELECT ord_status FROM dc_orders WHERE location='" +
                  self.location + "' AND clord_id='" + identifier(clid) + "'"),
                  lambda r: r == [[expected]], "order " + clid + " " + expected)

    def cancel(self, user):
        self.api("OrderSvr", "cancelAllOrder", {"UserID": user, "SecurityID": "BTCUSDT",
                 "MarketIndicator": "4", "AlgoName": "cross", "Location": self.location}, user)

    def account_check(self, user, balance, margin):
        actual = self.wait(lambda: self.balance(user),
                           lambda b: b and D(b["Balance"]) == balance and D(b["UsedMargin"]) == margin,
                           "account balance/margin")
        for field in ("FreezedMargin", "FreezedCommission"):
            self.equal(field, actual[field], 0)
        return {field: actual[field] for field in ("Balance", "UsedMargin", "FreezedMargin", "FreezedCommission")}

    def execute(self):
        maker, taker = self.register("maker"), self.register("taker")
        rates = {}
        for user in (maker, taker):
            config = self.api("TradeSvr", "getAccountConfig", {}, user)["data"]
            # Fix expected rates for this scenario; configuration mismatch is a gate failure.
            if not config or D(str(config["makerCommission"])) != D("0.0002") or D(str(config["takerCommission"])) != D("0.0006"):
                raise AssertionError("Test requires declared maker=0.0002/taker=0.0006 fee policy")
            rates[user] = config
            baseline = self.balance(user)
            if baseline:
                for field in ("Balance", "UsedMargin", "FreezedMargin", "FreezedCommission"):
                    self.equal("initial " + field, baseline[field], 0)
            position = self.position(user)
            for field in ("LongPosition", "ShortPosition"):
                self.equal("initial " + field, position[field], 0)
            self.api("TradeSvr", "setLeverage", {"userID": user, "securityID": "BTCUSDT",
                     "location": self.location, "leverage": 10}, user)
            self.api("TradeSvr", "cashIn", {"Amount": "1000", "UserID": user,
                     "Location": self.location, "Demo": "0"}, user)
            self.account_check(user, D(1000), D(0))
        self.record("fresh public-registration accounts funded through API", {"amountEach": "1000"})

        resting = self.order(taker, "Buy", D("0.0001"), D(70000), "CANCEL")
        self.order_status(resting, "New")
        self.cancel(taker)
        self.order_status(resting, "Canceled")
        self.record("cancel releases reserves", self.account_check(taker, D(1000), D(0)))

        q, p, close = D("0.0002"), D(83000), D(83100)
        opening = self.order(maker, "Sell", q, p, "OPEN-MAKER")
        self.order_status(opening, "New")
        for index in (1, 2):
            fill = self.order(taker, "Buy", q / 2, p, "OPEN-TAKER-" + str(index))
            self.order_status(fill, "Filled")
            self.order_status(opening, "Partially_Filled" if index == 1 else "Filled")
        fee_m, fee_t = money(q * p * D("0.0002")), money(q * p * D("0.0006"))
        for user, side, fee in ((maker, "Short", fee_m), (taker, "Long", fee_t)):
            pos = self.wait(lambda: self.position(user), lambda r: D(r[side + "Position"]) == q,
                            "open position")
            self.equal(side + "Average", pos[side + "Average"], p)
            margin = expected_margin(q, p, D(10), D("0.0006"), side)
            self.equal(side + "UsedMargin", pos[side + "UsedMargin"], margin)
            self.record("open " + side + " independent calculation", self.account_check(user, D(1000) - fee, margin))

        closing = self.order(maker, "Buy", q, close, "CLOSE-MAKER", "Short")
        self.order_status(closing, "New")
        fill = self.order(taker, "Sell", q, close, "CLOSE-TAKER", "Long")
        self.order_status(fill, "Filled")
        self.order_status(closing, "Filled")
        pnl = q * (close - p)
        for user, side, opening_fee, rate, realized in (
                (maker, "Short", fee_m, D("0.0002"), -pnl),
                (taker, "Long", fee_t, D("0.0006"), pnl)):
            expected = D(1000) - opening_fee - money(q * close * rate) + realized
            pos = self.wait(lambda: self.position(user),
                            lambda r: D(r["LongPosition"]) == 0 and D(r["ShortPosition"]) == 0,
                            "flat final position")
            for field in ("LongUsedMargin", "ShortUsedMargin", "LongLockedPosition", "ShortLockedPosition"):
                self.equal(field, pos[field], 0)
            self.record("close " + side + " PnL/fees/margin", self.account_check(user, expected, D(0)))
            self.verify_projection(user, expected)
        self.report["passed"] = True

    def verify_projection(self, user, expected):
        where = " WHERE location='" + self.location + "' AND user_id='" + user + "'"
        balance = self.wait(lambda: self.sql("SELECT balance,used_margin,freezed_margin,freezed_commission FROM dc_users_balance" + where),
                            lambda r: len(r) == 1 and list(map(D, r[0])) == [expected, D(0), D(0), D(0)],
                            "projected balance")
        postings = self.sql("SELECT COALESCE(SUM(CAST(amount AS DECIMAL(35,9))),0) FROM dc_users_posting" + where)[0][0]
        self.equal("posting sum reconciles final balance", postings, expected)
        self.equal("final active orders", self.sql("SELECT COUNT(*) FROM dc_orders" + where +
                   " AND ord_status IN ('New','Partially_Filled')")[0][0], 0)
        executions = self.sql("SELECT last_px,last_qty,fee,realized_Pnl,Maker FROM dc_orders_execorders" + where +
                              " ORDER BY last_px,last_qty")
        if len(executions) != 3:
            raise AssertionError("Expected exactly three execution records per fresh account")
        for px, qty, fee, realized, maker in executions:
            rate = D("0.0002") if user == self.accounts[0]["userId"] else D("0.0006")
            self.equal("execution fee", fee, -money(D(px) * D(qty) * rate))
            self.equal("maker flag", maker, 1 if user == self.accounts[0]["userId"] else 0)
            expected_pnl = (D(px) - D(83000)) * D(qty)
            if user == self.accounts[0]["userId"]:
                expected_pnl = -expected_pnl
            self.equal("execution realized PnL", realized, expected_pnl)
        self.record("projection executions/postings reconcile", {"userId": user, "balance": balance[0][0],
                    "postingSum": postings, "executions": len(executions)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:" + os.environ.get("WEB_LISTEN_PORT", "18088"))
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d%H%M%S"))
    parser.add_argument("--execute", action="store_true", help="register fresh users and perform six small orders")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    runner = Smoke(args.location, args.base_url, args.run_id)
    try:
        runner.preflight()
        if args.execute:
            runner.execute()
        else:
            runner.report["preflightOnly"] = True
    except (AssertionError, RuntimeError, ValueError) as error:
        runner.report["failure"] = str(error)
        print("[calculation-smoke] FAIL " + str(error), flush=True)
        runner.report["cleanup"] = []
        for user in runner.sessions:
            try:
                runner.cancel(user)
                pos = runner.position(user)
                runner.report["cleanup"].append({"userId": user, "restingCancelAccepted": True,
                    "longPosition": pos["LongPosition"], "shortPosition": pos["ShortPosition"]})
            except Exception:
                runner.report["cleanup"].append({"userId": user, "stateUnknown": True})
        runner.report["positionsAutoClosed"] = False
    Path(args.output).write_text(json.dumps(runner.report, indent=2, default=str) + "\n", encoding="utf-8")
    return 0 if runner.report.get("passed") or runner.report.get("preflightOnly") else 1


if __name__ == "__main__":
    raise SystemExit(main())
