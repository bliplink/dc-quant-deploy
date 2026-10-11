#!/usr/bin/env python3
"""One isolated Mac Demo Trade primary SIGKILL while a test user holds BTC."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone

from md_cluster_transition_host import DockerZk

ROOT = "/dc/cluster/tradesvr/partitions"
LOCATION = os.environ.get("TRADE_FAULT_LOCATION", "")
USER = os.environ.get("TRADE_FAULT_USER", "")
CONFIRM = "DEMO_TRADE_HELD_" + LOCATION
IMAGE = os.environ.get("TRADESVR_IMAGE_REPOSITORY", "") + ":" + os.environ.get("TRADESVR_TAG", "")
EVIDENCE = Path(os.environ.get("TRADE_CLUSTER_EVIDENCE_ROOT", "/tmp"))
zk = DockerZk("dc-saas-zookeeper", "127.0.0.1:32181", ROOT, "docker")

def command(*argv, timeout=45):
    return subprocess.run(argv, text=True, capture_output=True, check=True, timeout=timeout)

def read(partition):
    return zk.read(partition)["value"]

def sql_held():
    query = ("SELECT COUNT(*) FROM dc.dc_orders_position WHERE location='%s' AND user_id='%s' "
             "AND security_id='BTCUSDT' AND long_position=0.0001 AND COALESCE(short_position,0)=0"
             % (LOCATION, USER))
    result = command("docker", "exec", "-e", "MYSQL_PWD=" + os.environ["MYSQL_PASSWORD"],
                     "dc-saas-mysql", "mysql", "-u" + os.environ["MYSQL_USERNAME"],
                     "-N", "-e", query, timeout=20)
    return result.stdout.strip() == "1"

def main():
    if (not LOCATION.isalnum() or len(LOCATION) > 24 or
            not USER.isalnum() or len(USER) > 48 or
            os.environ.get("TRADE_FAULT_CONFIRM") != CONFIRM):
        raise RuntimeError("explicit isolated Trade fault token and identifiers required")
    if not IMAGE.startswith("dc-saas/tradesvr:cluster-dev-local-"):
        raise RuntimeError("refuse non-local Trade image")
    partition = "P%03d" % (zlib.crc32(LOCATION.encode()) % 256)
    original = read(partition)
    if not sql_held():
        raise RuntimeError("no verified held test position; refusing SIGKILL")
    if original["state"] != "READY" or original["primary"] == original.get("replica"):
        raise RuntimeError("Trade partition not ready with a distinct replica")
    primary = original["primary"]
    replica = original["replica"]
    if {primary, replica} != {"TradeSvrA", "TradeSvrB"}:
        raise RuntimeError("unexpected Trade topology")
    target = "dc-saas-tradesvr" if primary == "TradeSvrA" else "dc-saas-tradesvr-b"
    survivor = "dc-saas-tradesvr-b" if primary == "TradeSvrA" else "dc-saas-tradesvr"
    status = json.loads(command("docker", "inspect", target).stdout)[0]
    if (status["Config"]["Image"] != IMAGE or
            status["HostConfig"]["RestartPolicy"]["Name"] != "unless-stopped"
            or not status["State"]["Running"]):
        raise RuntimeError("Trade target image/restart/running gate failed")
    if json.loads(command("docker", "inspect", survivor).stdout)[0]["Config"]["Image"] != IMAGE:
        raise RuntimeError("Trade replica image mismatch")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    record = {"partition": partition, "location": LOCATION, "before": original,
              "startedUtc": started.isoformat(), "target": target}
    changed = False
    killed = False
    try:
        command("docker", "update", "--restart=no", target)
        changed = True
        command("docker", "kill", "--signal=KILL", target)
        killed = True
        record["killedUtc"] = datetime.now(timezone.utc).isoformat()
        print("[trade-fault] SIGKILL %s while %s holds 0.0001 BTC" % (target, LOCATION), flush=True)
        deadline = time.monotonic() + 330
        promoted = None
        while time.monotonic() < deadline:
            after = read(partition)
            if (after["primary"] == replica and after["epoch"] > original["epoch"]
                    and after["state"] == "READY"):
                promoted = after
                break
            time.sleep(3)
        record["afterFailover"] = promoted or read(partition)
        if promoted is None:
            raise RuntimeError("automatic Trade failover did not promote replica")
        print("[trade-fault] promoted=%s epoch=%s" % (replica, promoted["epoch"]), flush=True)
        marker = "TRADE_PARTITION_READY node:%s, partition:%s, epoch:%s" % (
            replica, partition, promoted["epoch"])
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            log = command("docker", "logs", "--since", started.isoformat(timespec="seconds"),
                          survivor, timeout=20)
            if marker in log.stdout + log.stderr:
                record["promotionReady"] = True
                break
            time.sleep(2)
        if not record.get("promotionReady"):
            raise RuntimeError("promoted Trade node lacks matching READY evidence")
        if not sql_held():
            raise RuntimeError("held position changed in authoritative MySQL")
        record["status"] = "PASS_AUTOMATIC_TRADE_TAKEOVER_HELD_POSITION"
    except Exception as exc:
        record["status"] = "FAIL"
        record["error"] = str(exc)
        raise
    finally:
        if killed:
            try:
                command("docker", "start", target, timeout=90)
                record["targetRestarted"] = True
            except Exception as exc:
                record["targetRestartError"] = str(exc)
        if changed:
            try:
                command("docker", "update", "--restart=unless-stopped", target)
                record["restartPolicyRestored"] = True
            except Exception as exc:
                record["policyError"] = str(exc)
        record["afterRestart"] = read(partition)
        path = EVIDENCE / ("trade-sigkill-" + started.strftime("%Y%m%dT%H%M%SZ") + ".json")
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print("[trade-fault] status=%s evidence=%s" % (record["status"], path), flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[trade-fault] FAIL " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
