#!/usr/bin/env python3
"""Guarded Mac Demo Trade epoch-1 empty partition SIGKILL test.

Only this isolated dc-saas local cluster is eligible. Does not mutate
partition assignments; the failover controller alone must promote the replica.
Always attempts to restart the killed container and restore its restart policy.
"""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from md_cluster_transition_host import DockerZk

PARTITION = os.environ.get("TRADE_EMPTY_FAULT_PARTITION", "")
CONFIRM = "MAC_DEMO_TRADE_EMPTY_" + PARTITION + "_KILL_A"
IMAGE = "dc-saas/tradesvr:cluster-dev-local-tradeempty-a8fc334-20261011"
NODE = "dc-saas-tradesvr"
REPLICA = "dc-saas-tradesvr-b"
ZK = DockerZk("dc-saas-zookeeper", "127.0.0.1:32181",
              "/dc/cluster/tradesvr/partitions", "docker")


def run(*args, timeout=60):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def read():
    return ZK.read(PARTITION)["value"]


def inspect(container):
    return json.loads(run("docker", "inspect", container).stdout)[0]


def main():
    if (not PARTITION.startswith("P") or len(PARTITION) != 4
            or not PARTITION[1:].isdigit()
            or int(PARTITION[1:]) >= 256
            or os.environ.get("TRADE_EMPTY_FAULT_CONFIRM") != CONFIRM):
        raise RuntimeError("exact Mac Demo fault token and valid partition required")
    original = read()
    if (original.get("epoch") != 1 or original.get("state") != "READY"
            or original.get("primary") != "TradeSvrA"
            or original.get("replica") != "TradeSvrB"):
        raise RuntimeError("target must be pristine READY Trade A->B epoch 1")
    runtime_root = Path(os.environ["DEPLOY_ROOT"])
    snapshot_path = runtime_root / "data" / "TradeSvrB" / "snapshot" / PARTITION / "latest.json"
    snapshot = json.loads(snapshot_path.read_text())
    if (snapshot.get("epoch") != 1 or snapshot.get("snapshotSeq") != 0
            or snapshot.get("committedStateSeq") != 0
            or snapshot.get("committedStateEpoch") != 0
            or any(snapshot.get(x) for x in (
                "balances", "positions", "locations", "accountConfigs", "symbolParas", "openOrders"))):
        raise RuntimeError("hot replica lacks durable pristine empty baseline")
    primary = inspect(NODE)
    replica = inspect(REPLICA)
    if (primary["Config"]["Image"] != IMAGE or replica["Config"]["Image"] != IMAGE
            or primary["HostConfig"]["RestartPolicy"]["Name"] != "unless-stopped"
            or not primary["State"]["Running"] or not replica["State"]["Running"]):
        raise RuntimeError("both Trade nodes must use verified local proof image")
    evidence_root = Path(os.environ["TRADE_EMPTY_FAULT_EVIDENCE"])
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    started = dt.datetime.now(dt.timezone.utc)
    record = {
        "partition": PARTITION, "original": original,
        "startedUtc": started.isoformat(), "image": IMAGE,
        "snapshotSeq": 0, "action": "SIGKILL Trade A, watch automatic replica"
    }
    changed = False
    killed = False
    try:
        run("docker", "update", "--restart=no", NODE)
        changed = True
        run("docker", "kill", "--signal=KILL", NODE)
        killed = True
        record["killedUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        print("[trade-empty-fault] killed Trade A; waiting for " + PARTITION, flush=True)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            after = read()
            if (after.get("primary") == "TradeSvrB"
                    and after.get("epoch", 0) > original["epoch"]
                    and after.get("state") == "READY"):
                record["afterPromotion"] = after
                record["promotedUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                break
            time.sleep(3)
        if "afterPromotion" not in record:
            raise RuntimeError("empty partition did not automatically promote")
        marker = ("TRADE_PARTITION_READY node:TradeSvrB, partition:%s, epoch:%s"
                  % (PARTITION, record["afterPromotion"]["epoch"]))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            logs = run("docker", "logs", "--since", started.isoformat(timespec="seconds"),
                       REPLICA, timeout=20)
            if marker in logs.stdout + logs.stderr:
                record["promotionReady"] = True
                break
            time.sleep(2)
        if not record.get("promotionReady"):
            raise RuntimeError("Trade replica has not passed recovery READY")
        record["result"] = "PASS_EMPTY_INITIAL_PARTITION_AUTO_TAKEOVER"
    except Exception as exc:
        record["result"] = "FAIL"
        record["error"] = str(exc)
        raise
    finally:
        if killed:
            try:
                run("docker", "start", NODE, timeout=90)
                record["nodeRestored"] = True
            except Exception as exc:
                record["nodeRestoredError"] = str(exc)
        if changed:
            try:
                run("docker", "update", "--restart=unless-stopped", NODE)
                record["restartPolicyRestored"] = True
            except Exception as exc:
                record["policyRestoredError"] = str(exc)
        record["afterRestore"] = read()
        outfile = evidence_root / ("trade-empty-" + PARTITION.lower() + "-"
                                   + started.strftime("%Y%m%dT%H%M%SZ") + ".json")
        outfile.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print("[trade-empty-fault] %s; evidence=%s" % (record["result"], outfile), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[trade-empty-fault] FAIL: %s" % exc, file=sys.stderr)
        sys.exit(1)
