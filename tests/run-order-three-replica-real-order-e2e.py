#!/usr/bin/env python3
"""Current Mac Demo Order A/B/C live GTC order survival across two epoch CAS transitions.

Acceptance-only: creates a dedicated trial tenant and trader through public APIs.
Never stops containers, bypasses readiness, or removes any required sync replica.
"""
import importlib.util
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from md_cluster_transition_host import DockerZk

src = Path(__file__).with_name("run-auto-tenant-trading-e2e.py")
spec = importlib.util.spec_from_file_location("order_trial_api", src)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

NODES = ("OrderSvrA", "OrderSvrB", "OrderSvrC")
ZK = DockerZk("dc-saas-zookeeper", "127.0.0.1:32181",
              "/dc/cluster/ordersvr/partitions", "docker")
ROOT = Path(os.environ.get("ORDER_CLUSTER_DATA_ROOT",
            "/Users/kong/.opentradingcore/dc-saas-runtime-ordered-20261015/data"))
EVIDENCE = Path(os.environ.get("ORDER_LIVE_ROLE_EVIDENCE_ROOT",
                str(Path.home() / ".opentradingcore" / "cluster-evidence")))
RUN = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + secrets.token_hex(2)
results = {"run": RUN, "type": "order-live-triple-replica-gtc-role-reversal",
           "transitions": [], "status": "RUNNING"}

def log(msg):
    print("[order-3rep-live-gtc] " + msg, flush=True)

def wait(label, probe, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result:
                return result
        except (RuntimeError, OSError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(label + " did not converge within " + str(seconds) + "s")

def market_key(loc):
    return loc + "\x1f4\x1fBTCUSDT"

def partition(loc):
    return "P%03d" % (zlib.crc32(market_key(loc).encode()) % 256)

def get_orders(token, loc, user):
    data = api.call("OrderSvr", "queryOpenOrder",
                    {"userid": user, "securityid": "BTCUSDT", "Location": loc},
                    token, key=market_key(loc))
    return json.dumps(data, ensure_ascii=False)

def ready(node, part, epoch, since):
    container = {"OrderSvrA": "dc-saas-ordersvr", "OrderSvrB": "dc-saas-ordersvr-b"}[node]
    marker = "ORDER_PARTITION_PROMOTION_READY node:%s, partition:%s, epoch:%d" % (node, part, epoch)
    def probe():
        p = subprocess.run(["docker", "logs", "--since", since, container],
                           capture_output=True, text=True, timeout=20)
        return p.returncode == 0 and marker in p.stdout + p.stderr
    wait("promotion READY " + node + " epoch " + str(epoch), probe, 140)
    log("READY " + node + " epoch=" + str(epoch))

def switch(part, original_node, new_node):
    record = ZK.read(part)
    value = record["value"]
    if (value.get("primary") != original_node or value.get("state") != "READY"
            or set(value.get("replicas", [])) != set(NODES) - {original_node}
            or len(value.get("replicas", [])) != 2):
        raise RuntimeError("wrong live 3-replica topology before CAS")
    replicas = [original_node, "OrderSvrC"] if new_node != "OrderSvrC" else []
    if set(replicas) != set(NODES) - {new_node}:
        raise RuntimeError("refusing to lose required replica")
    desired = dict(value)
    desired.update({"primary": new_node, "replica": replicas[0],
                    "replicas": replicas, "epoch": value["epoch"] + 1,
                    "assignmentVersion": value["assignmentVersion"] + 1})
    after = ZK.cas(record, desired)
    epoch = after["value"]["epoch"]
    results["transitions"].append({"from": original_node, "to": new_node, "epoch": epoch})
    log("CAS " + original_node + " -> " + new_node + " epoch=" + str(epoch))
    return epoch

def preflight(part, loc):
    z = ZK.read(part)["value"]
    if z.get("state") != "READY" or z.get("primary") not in NODES[:2]:
        raise RuntimeError("initial partition not routable")
    if set(z.get("replicas", [])) != set(NODES) - {z["primary"]}:
        raise RuntimeError("not exactly A/B/C synchronous topology")
    routes = api.sql("SELECT s.location,s.market_indicator,s.security_id "
                     "FROM dc_tenant_symbol s JOIN dc_tenant t ON t.location=s.location "
                     "WHERE t.status IN ('ACTIVE','TRIAL') AND s.enabled=1")
    for row in routes:
        if len(row) != 3 or row[0] == loc:
            continue
        if zlib.crc32("\x1f".join(row).encode()) % 256 == int(part[1:]):
            raise RuntimeError("active market shares test partition")
    def image_ok():
        hashes = []
        for node in NODES:
            f = ROOT / node / "snapshot" / part / "snapshot.json"
            if not f.is_file() or f.is_symlink():
                return False
            raw = f.read_bytes()
            data = json.loads(raw)
            if (data["partitionId"] != part or data["epoch"] != z["epoch"]
                    or data.get("commitMarkerSeq", 0) <= 0):
                return False
            if not any(b.get("location") == loc for b in data.get("books", [])):
                return False
            hashes.append(hashlib.sha256(raw).digest())
        return len(set(hashes)) == 1
    wait("triplicate committed image", image_ok, 100)
    return z["primary"]

def main():
    rid = "ORDER_3REP_" + RUN
    email = "order3rep-" + RUN.lower() + "@example.invalid"
    user = "order3rep" + secrets.token_hex(3)
    password = secrets.token_urlsafe(24)
    application = api.call("ManagerSvr", "tenantApplication", {
        "action": "SUBMIT", "cid": rid, "request_id": rid,
        "organization_name": "Order Three-Replica HA " + RUN,
        "contact_name": "Acceptance", "contact_email": email,
        "expected_users": 2, "requested_symbols": ["BTCUSDT"],
        "requested_trial_days": 30, "admin_password": secrets.token_urlsafe(24)
    })
    approval = api.call("ManagerSvr", "tenantApplication", {
        "action": "STATUS", "application_id": application["application_id"],
        "contact_email": email})
    if approval["status"] != "APPROVED":
        raise RuntimeError("test tenant auto-approval failed")
    loc = approval["approved_location"]
    api.LOCATION = loc
    part = partition(loc)
    results.update({"location": loc, "partition": part})
    log("approved isolated location=" + loc + " orderPartition=" + part)
    wait("Robot bootstrap", lambda: api.sql(
        "SELECT runtime_status,open_order_count FROM dc_tenant_robot WHERE location='%s'" % loc
    ) == [["RUNNING", "40"]], 180)
    wait("market quotes", lambda: len(api.market_entries()) >= 20, 70)
    original = preflight(part, loc)
    reg = api.call("AdminSvr", "tenantUserRegistration", {
        "action": "REGISTER", "cid": "REGISTER_" + rid, "request_id": "REGISTER_" + rid,
        "location": loc, "username": user, "name": "Order 3 replica acceptance trader",
        "email": user + "@example.invalid", "password": password})
    uid = reg["user_id"]
    login = api.call("LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": "LOGIN_" + rid, "user_id": user,
        "user_name": user, "password": password,
        "client_type": "WEB", "Location": loc})
    token = login["token"]
    api.call("TradeSvr", "cashIn", {
        "Amount": "1000", "UserID": uid, "Location": loc, "Demo": "1"
    }, token, key=loc)
    bids, asks = api.market_book()
    if not bids or not asks:
        raise RuntimeError("live book missing")
    price = (max(bids) - Decimal("100")).quantize(Decimal("0.1"))
    cid = "O3REP-" + RUN
    accepted = False
    try:
        api.call("OrderSvr", "placeOrder", {
            "OCType": "OPEN", "OrderQty": "0.0001", "OrdType": "Limit",
            "ClOrdID": cid, "Terminal": "TripleReplicaHA", "AlgoName": "cross",
            "Side": "Buy", "Price": str(price), "UserID": uid,
            "MarketIndicator": "4", "TimeInForce": "GTC",
            "SecurityID": "BTCUSDT", "Location": loc
        }, token, key=market_key(loc))
        accepted = True
        wait("GTC accepted and queryable", lambda: cid in get_orders(token, loc, uid), 55)
        results["acknowledgedOrder"] = cid
        log("LIVE_GTC_QUERYABLE " + cid)
        target = "OrderSvrB" if original == "OrderSvrA" else "OrderSvrA"
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ep = switch(part, original, target)
        ready(target, part, ep, started)
        wait("order queryable on promoted primary", lambda: cid in get_orders(token, loc, uid), 65)
        results["transitions"][-1]["orderSurvived"] = True
        log("GTC_SURVIVED_PROMOTED_" + target)
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ep = switch(part, target, original)
        ready(original, part, ep, started)
        wait("order queryable on restored primary", lambda: cid in get_orders(token, loc, uid), 65)
        results["transitions"][-1]["orderSurvived"] = True
        log("GTC_SURVIVED_RESTORED_" + original)
        results["status"] = "PASS"
    finally:
        current = ZK.read(part)["value"]
        if current["primary"] != original:
            if current["primary"] in NODES[:2] and current["state"] == "READY":
                try:
                    ep = switch(part, current["primary"], original)
                    ready(original, part, ep, datetime.now(timezone.utc).isoformat(timespec="seconds"))
                except Exception as e:
                    results["restoreError"] = repr(e)
                    results["status"] = "FAIL_NEEDS_RESTORE"
            else:
                results["status"] = "FAIL_UNEXPECTED_PRIMARY"
        if accepted and ZK.read(part)["value"]["primary"] == original:
            try:
                api.call("OrderSvr", "cancelAllOrder", {
                    "UserID": uid, "SecurityID": "BTCUSDT", "MarketIndicator": "4",
                    "AlgoName": "cross", "Location": loc
                }, token, key=market_key(loc))
                wait("GTC cancellation", lambda: cid not in get_orders(token, loc, uid), 65)
                results["orderCancelled"] = True
                log("GTC_CANCELLED")
            except Exception as e:
                results["cleanupError"] = repr(e)
                results["status"] = "FAIL_CLEANUP"
        EVIDENCE.mkdir(mode=0o700, parents=True, exist_ok=True)
        dest = EVIDENCE / ("order-3rep-live-gtc-" + RUN + ".json")
        results["finalAssignment"] = ZK.read(part)["value"]
        dest.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        log("RESULT=" + results["status"] + " evidence=" + str(dest))
    if results["status"] != "PASS":
        raise RuntimeError("HA order test did not finish cleanly")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FAIL " + type(exc).__name__ + ": " + str(exc)[:290])
        sys.exit(1)

