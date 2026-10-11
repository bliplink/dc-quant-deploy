#!/usr/bin/env python3
"""Cold Demo only: guarded OrderA SIGKILL and automatic partition takeover probe.

This deliberately tests a three-node cluster with two live synchronous replicas,
never production. No assignment edits or order writes are performed. Export the
protected Demo runtime env plus OTC_DEMO_FAULT_LOCATION and OTC_DEMO_FAULT_PARTITION;
OTC_DEMO_FAULT_CONFIRM must equal DEMO_<LOCATION>_<PARTITION>_ORDER_A_SIGKILL.
"""
import datetime as dt
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import zlib

LOCATION = os.environ.get("OTC_DEMO_FAULT_LOCATION", "")
PARTITION = os.environ.get("OTC_DEMO_FAULT_PARTITION", "")
ZK_PATH = "/dc/cluster/ordersvr/partitions/" + PARTITION
NODE = "dc-saas-ordersvr"
RESTART = "unless-stopped"
CONFIRM = "DEMO_" + LOCATION + "_" + PARTITION + "_ORDER_A_SIGKILL"
EXPECTED_IMAGE = os.environ.get("ORDERSVR_IMAGE_REPOSITORY", "") + ":" + os.environ.get("ORDERSVR_TAG", "")
TIMEOUT = 300

def run(*argv, input=None, timeout=30):
    return subprocess.run(argv, input=input, text=True, capture_output=True,
                          timeout=timeout, check=True).stdout

def assignment():
    raw = run("docker", "exec", "-i", "dc-saas-zookeeper", "zkCli.sh",
              "-server", "127.0.0.1:32181", input="get " + ZK_PATH + "\nquit\n", timeout=25)
    rows = [json.loads(x) for x in raw.splitlines() if x.startswith("{")]
    if len(rows) != 1 or rows[0].get("partitionId") != PARTITION:
        raise RuntimeError("ambiguous ZooKeeper assignment")
    return rows[0]

def container(name):
    return json.loads(run("docker", "inspect", name))[0]

def book():
    url = "http://127.0.0.1:" + os.environ.get("WEB_LISTEN_PORT", "18088") + "/httpapi/"
    payload = {"serverName": "MDSvr", "method": "queryPublicMarket",
               "key": LOCATION + "\x1f4\x1fBTCUSDT",
               "content": {"location": LOCATION, "securityID": "BTCUSDT"}}
    req = urllib.request.Request(url, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15) as r:
        response = json.load(r)
    if response.get("code") != 0:
        raise RuntimeError("MD routing not healthy: " + str(response.get("code")))
    entries = ((response.get("data") or {}).get("orderBook") or {}).get("NoMDEntries") or []
    sides = [sum(str(x.get("MDEntryType")) == side for x in entries) for side in ("0", "1")]
    return sides

def main():
    if not re.fullmatch(r"[A-Z0-9]{3,20}", LOCATION) or not re.fullmatch(r"P\d{3}", PARTITION):
        raise RuntimeError("safe demo location/partition identifiers are required")
    if (not os.environ.get("ORDERSVR_IMAGE_REPOSITORY") or
            not os.environ.get("ORDERSVR_TAG")):
        raise RuntimeError("protected Demo deployment image lock must be exported")
    if os.environ.get("OTC_DEMO_FAULT_CONFIRM") != CONFIRM:
        raise RuntimeError("explicit isolated demo fault confirmation required")
    expected_index = int(PARTITION[1:])
    if expected_index >= 256 or zlib.crc32((LOCATION + "\x1f4\x1fBTCUSDT").encode()) % 256 != expected_index:
        raise RuntimeError("business key does not map to selected partition")
    before = assignment()
    if (before.get("primary") != "OrderSvrA" or
        before.get("state") != "READY" or
        set(before.get("replicas") or []) != {"OrderSvrB", "OrderSvrC"}):
        raise RuntimeError("P238 is not the expected A/B/C READY assignment")
    for name in (NODE, "dc-saas-ordersvr-b", "dc-saas-ordersvr-c",
                 "dc-saas-gateway", "dc-saas-zookeeper", "dc-saas-robotsvr"):
        inspect = container(name)
        if not inspect["State"]["Running"]:
            raise RuntimeError("prerequisite not running: " + name)
    original = container(NODE)
    if original["HostConfig"]["RestartPolicy"]["Name"] != RESTART:
        raise RuntimeError("unexpected restart policy")
    if original["Config"]["Image"] != EXPECTED_IMAGE or "cluster-dev-local-" not in EXPECTED_IMAGE:
        raise RuntimeError("unexpected Order image; only locked local Demo image is allowed")
    if min(book()) < 1:
        raise RuntimeError("pre-fault Robot public order book empty")

    evidence_root = Path(os.environ.get("OTC_HA_EVIDENCE_ROOT", "/tmp"))
    evidence_root.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    record = {"runAtUtc": started.isoformat(), "partition": PARTITION,
              "location": LOCATION, "image": original["Config"]["Image"],
              "before": before, "safety": "isolated Demo only",
              "action": "SIGKILL order A with restart policy temporarily disabled"}
    changed_restart = False
    killed = False
    try:
        run("docker", "update", "--restart=no", NODE)
        changed_restart = True
        run("docker", "kill", "--signal=KILL", NODE)
        killed = True
        record["killedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        print("[order-fault] SIGKILL Order A, monitoring P238", flush=True)
        deadline = time.monotonic() + TIMEOUT
        takeover = None
        while time.monotonic() < deadline:
            current = assignment()
            if current.get("primary") in ("OrderSvrB", "OrderSvrC") and \
                    current.get("state") == "READY" and int(current["epoch"]) > int(before["epoch"]):
                takeover = current
                break
            time.sleep(3)
        record["afterFailover"] = takeover or assignment()
        record["failoverSeconds"] = round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 3)
        if takeover is None:
            raise RuntimeError("automatic P238 primary takeover did not converge")
        print("[order-fault] P238 new primary=%s epoch=%s" %
              (takeover["primary"], takeover["epoch"]), flush=True)
        # The primary must fully recover; a ZooKeeper assignment alone is not READY.
        ready_marker = "ORDER_PARTITION_PROMOTION_READY node:%s, partition:%s, epoch:%d" % (
            takeover["primary"], PARTITION, takeover["epoch"])
        target_name = "dc-saas-ordersvr-b" if takeover["primary"] == "OrderSvrB" else "dc-saas-ordersvr-c"
        deadline = time.monotonic() + 120
        ready = False
        while time.monotonic() < deadline:
            fetched = subprocess.run(["docker", "logs", "--since", started.isoformat(timespec="seconds"), target_name],
                                     capture_output=True, text=True, timeout=20, check=True)
            if ready_marker in fetched.stdout + fetched.stderr:
                ready = True
                break
            time.sleep(2)
        record["promotionReady"] = ready
        if not ready:
            raise RuntimeError("new primary assignment has not passed snapshot promotion READY")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                sides = book()
                if min(sides) >= 1:
                    record["postFailoverVisibleBook"] = sides
                    break
            except Exception:
                pass
            time.sleep(3)
        if "postFailoverVisibleBook" not in record:
            raise RuntimeError("market data never recovered after Order failover")
        record["result"] = "PASS_AUTO_TAKEOVER_AND_MARKET_READS"
    except Exception as exc:
        record["result"] = "FAIL"
        record["error"] = repr(exc)
        raise
    finally:
        if killed:
            try:
                run("docker", "start", NODE, timeout=60)
                record["orderARestarted"] = True
            except Exception as exc:
                record["orderARestarted"] = False
                record["restartError"] = repr(exc)
        if changed_restart:
            try:
                run("docker", "update", "--restart=" + RESTART, NODE)
                record["restartPolicyRestored"] = True
            except Exception as exc:
                record["restartPolicyRestored"] = False
                record["policyError"] = repr(exc)
        record["afterRestart"] = assignment()
        path = evidence_root / ("order-" + PARTITION.lower() + "-sigkill-" + started.strftime("%Y%m%dT%H%M%SZ") + ".json")
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print("[order-fault] result=%s restarted=%s restartPolicyRestored=%s evidence=%s" %
              (record.get("result"), record.get("orderARestarted"), record.get("restartPolicyRestored"), path), flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[order-fault] FAIL: " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
