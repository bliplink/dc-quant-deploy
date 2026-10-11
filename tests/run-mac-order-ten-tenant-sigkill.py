#!/usr/bin/env python3
"""Strictly scoped Mac Demo: SIGKILL all-primary Order B with ten live tenants.

No partition assignment or business database mutations are made by this
program. The existing automatic HA controller must elect a synchronized
replica. Always attempt Docker restart/policy restoration and write evidence.
Usage: export the *locked* Demo ENV_FILE then set
ORDER_10_FAULT_CONFIRM=MAC_DEMO_TEN_ORDER_B_SIGKILL.
"""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from md_cluster_transition_host import DockerZk

CONFIRM = "MAC_DEMO_TEN_ORDER_B_SIGKILL"
NODE = "dc-saas-ordersvr-b"
TARGET = "P238"
COUNT = 256
EVIDENCE = Path(os.environ.get("ORDER_10_FAULT_EVIDENCE", "/tmp"))
zk = DockerZk("dc-saas-zookeeper", "127.0.0.1:32181",
              "/dc/cluster/ordersvr/partitions", "docker")


def command(*argv, timeout=50):
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=timeout)


def inspect(name):
    return json.loads(command("docker", "inspect", name).stdout)[0]


def read():
    return zk.read(TARGET)["value"]


def main():
    if os.environ.get("ORDER_10_FAULT_CONFIRM") != CONFIRM:
        raise RuntimeError("explicit isolated Demo confirmation required")
    expected = os.environ.get("ORDERSVR_IMAGE_REPOSITORY", "") + ":" + os.environ.get("ORDERSVR_TAG", "")
    if "cluster-dev-local-" not in expected:
        raise RuntimeError("locked locally-built Order image required")
    primary = inspect(NODE)
    if (not primary["State"]["Running"]
            or primary["Config"]["Image"] != expected
            or primary["HostConfig"]["RestartPolicy"]["Name"] != "unless-stopped"
            or primary["State"]["OOMKilled"]):
        raise RuntimeError("Order B must be healthy on the verified local image")
    for other in ("dc-saas-ordersvr", "dc-saas-ordersvr-c",
                  "dc-saas-zookeeper", "dc-saas-tradesvr",
                  "dc-saas-tradesvr-b", "dc-saas-robotsvr"):
        status = inspect(other)
        if not status["State"]["Running"] or status["State"]["OOMKilled"]:
            raise RuntimeError("prerequisite not running/healthy: " + other)
    initial = read()
    if (initial.get("primary") != "OrderSvrB"
            or initial.get("state") != "READY"
            or set(initial.get("replicas") or []) != {"OrderSvrA", "OrderSvrC"}):
        raise RuntimeError("P238 not a ready B-primary with two synchronized replicas")
    # The 256/256 snapshot and topology preflight must have been run explicitly
    # by the operator. Requiring its evidence prevents accidental broad kills.
    preflight = Path(os.environ.get("ORDER_10_FAULT_PREFLIGHT", ""))
    if not preflight.is_file():
        raise RuntimeError("verified preflight artifact file required")
    pre = json.loads(preflight.read_text())
    checked = dt.datetime.fromisoformat(pre.get("checkedUtc", ""))
    if checked.tzinfo is None or (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 600:
        raise RuntimeError("stale 256/256 safety preflight")
    if (pre.get("ready") != COUNT or pre.get("primaryB") != COUNT
            or pre.get("replicaAC") != COUNT or pre.get("snapshotConsistent") != COUNT
            or pre.get("tenants") != 10
            or pre.get("status") != "PASS"):
        raise RuntimeError("256/256 preflight evidence not complete")
    EVIDENCE.mkdir(mode=0o700, parents=True, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    record = {"startedUtc": started.isoformat(), "image": expected,
              "partition": TARGET, "before": initial,
              "preflight": str(preflight),
              "action": "SIGKILL all-primary Order B, promote hot replica"}
    changed = False
    killed = False
    try:
        command("docker", "update", "--restart=no", NODE)
        changed = True
        command("docker", "kill", "--signal=KILL", NODE)
        killed = True
        record["killedUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        print("[order-ten-fault] SIGKILL Order B; observing " + TARGET, flush=True)
        deadline = time.monotonic() + 360
        promoted = None
        while time.monotonic() < deadline:
            state = read()
            if (state.get("primary") in ("OrderSvrA", "OrderSvrC")
                    and int(state.get("epoch", 0)) > int(initial["epoch"])
                    and state.get("state") == "READY"):
                promoted = state
                break
            time.sleep(4)
        record["afterPromotion"] = promoted or read()
        record["convergenceSeconds"] = round(
            (dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2)
        if promoted is None:
            raise RuntimeError("P238 failed automatic primary election within 360s")
        name = "dc-saas-ordersvr" if promoted["primary"] == "OrderSvrA" else "dc-saas-ordersvr-c"
        marker = ("ORDER_PARTITION_PROMOTION_READY node:%s, partition:%s, epoch:%s"
                  % (promoted["primary"], TARGET, promoted["epoch"]))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            logs = command("docker", "logs", "--since",
                           started.isoformat(timespec="seconds"), name,
                           timeout=25)
            if marker in logs.stdout + logs.stderr:
                record["promotionReady"] = True
                break
            time.sleep(3)
        if not record.get("promotionReady"):
            raise RuntimeError("new primary has no matching snapshot promotion READY marker")
        record["result"] = "PASS_PRIMARY_ELECTED_AND_PROMOTION_READY"
        print("[order-ten-fault] PASS %s -> %s epoch %s -> %s, secs=%s" %
              (initial["primary"], promoted["primary"],
               initial["epoch"], promoted["epoch"], record["convergenceSeconds"]),
              flush=True)
    except Exception as exc:
        record["result"] = "FAIL"
        record["error"] = repr(exc)
        raise
    finally:
        if killed:
            try:
                command("docker", "start", NODE, timeout=90)
                record["nodeRestored"] = True
            except Exception as exc:
                record["nodeRestoredError"] = repr(exc)
        if changed:
            try:
                command("docker", "update", "--restart=unless-stopped", NODE)
                record["restartPolicyRestored"] = True
            except Exception as exc:
                record["policyRestoredError"] = repr(exc)
        record["afterRestore"] = read()
        path = EVIDENCE / ("order-ten-kill-" + started.strftime("%Y%m%dT%H%M%SZ") + ".json")
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print("[order-ten-fault] result=%s restored=%s policyRestored=%s evidence=%s" %
              (record.get("result"), record.get("nodeRestored"),
               record.get("restartPolicyRestored"), path), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[order-ten-fault] FAIL: %s" % exc, file=sys.stderr, flush=True)
        sys.exit(1)
