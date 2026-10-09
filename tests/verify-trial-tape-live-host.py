#!/usr/bin/env python3
"""Read-only live Tape canary gate: actual market trades and durable Trade postings.

A Demo=1 IOC may be visible in MDSvr recentTrades and Trade postings even when
there is no dc_orders_execorders row for that internal robot trade. Do not use
historical execution row count alone to judge whether Tape is working.
Run with the existing deployment env exported; never print API credentials.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

def mysql(query):
    env = os.environ.copy()
    if not env.get("MYSQL_PASSWORD") or not env.get("MYSQL_USERNAME"):
        raise RuntimeError("Export MYSQL_PASSWORD and MYSQL_USERNAME from the deploy env")
    env["MYSQL_PWD"] = env["MYSQL_PASSWORD"]
    result = subprocess.run(
        ["docker", "exec", "-i", "-e", "MYSQL_PWD",
         os.environ.get("MYSQL_CONTAINER", "dc-saas-mysql"), "mysql",
         "-u" + env["MYSQL_USERNAME"], "-N", "dc", "-e", query],
        check=True, capture_output=True, text=True, timeout=20, env=env)
    return [row.split("\t") for row in result.stdout.strip().splitlines()]

def market(url, location):
    request = {
        "serverName": "MDSvr", "method": "queryPublicMarket",
        "content": {"securityID": "BTCUSDT", "location": location},
        "key": location + "\x1f4\x1fBTCUSDT",
    }
    req = urllib.request.Request(
        url, json.dumps(request).encode("utf-8"),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.load(response)
    if result.get("code") != 0:
        raise RuntimeError("MDSvr.queryPublicMarket failed")
    data = result.get("data") or {}
    orders = ((data.get("orderBook") or {}).get("NoMDEntries") or [])
    trades = ((data.get("recentTrades") or {}).get("NoMDEntries") or [])
    bids = sum(str(x.get("MDEntryType")) == "0" for x in orders)
    asks = sum(str(x.get("MDEntryType")) == "1" for x in orders)
    if bids < 10 or asks < 10 or not trades:
        raise RuntimeError("Maker book or recentTrades is not ready")
    return len(trades), str(trades[-1].get("MDEntryID")), trades[-1].get("MDEntryTime")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", default=os.environ.get("TRIAL_LIQUIDITY_TAPE_CANARY_LOCATION", ""))
    parser.add_argument("--observe-seconds", type=float, default=12)
    parser.add_argument("--endpoint", default="http://127.0.0.1:{}/httpapi/".format(
        os.environ.get("WEB_LISTEN_PORT", "18088")))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z0-9]{6}", args.location):
        raise RuntimeError("canary location must be 6 uppercase letters/digits")
    if not 1 <= args.observe_seconds <= 120:
        raise RuntimeError("observe-seconds must be between 1 and 120")
    loc = args.location
    state = mysql(
        "SELECT b.status,b.step,b.tape_enabled,b.tape_funding_confirmed,"
        "r.enabled,r.runtime_status,r.open_order_count "
        "FROM dc_tenant_liquidity_bootstrap b "
        "JOIN dc_tenant_robot r ON r.location=b.location "
        "WHERE b.location='{}' AND r.robot_id='trial-liquidity-BTCUSDT';".format(loc))
    if len(state) != 1 or state[0][:6] != ["COMPLETE", "DONE", "1", "1", "1", "RUNNING"]             or int(state[0][6]) < 40:
        raise RuntimeError("Tape bootstrap or 40-level maker Robot is not healthy")
    count_sql = (
        "SELECT COUNT(*) FROM dc_users_posting p JOIN dc_tenant_liquidity_bootstrap b "
        "ON b.location=p.location AND b.tape_user_id=p.user_id "
        "WHERE b.location='{}' AND p.source='Trade';".format(loc))
    before_postings = int(mysql(count_sql)[0][0])
    first = market(args.endpoint, loc)
    time.sleep(args.observe_seconds)
    second = market(args.endpoint, loc)
    after_postings = int(mysql(count_sql)[0][0])
    if second[1] == first[1] or after_postings <= before_postings:
        raise RuntimeError("No live Tape execution or durable Trade posting growth")
    print("[trial-tape-live] PASS location={} recentTrades={} lastTrade={} postings={} (+{})"
          .format(loc, second[0], second[2], after_postings,
                  after_postings - before_postings))

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("[trial-tape-live] FAIL: {}".format(type(error).__name__ + ": " + str(error)),
              file=sys.stderr)
        sys.exit(1)
