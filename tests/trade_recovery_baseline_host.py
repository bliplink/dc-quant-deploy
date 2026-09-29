#!/usr/bin/env python3
"""Read-only Trade recovery baseline. Never changes assignments or containers.

READY is current-process, current-assignment log evidence, not an authenticated
business probe. Do not label this report as a failover or RPO acceptance result.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

try:
    from tests.md_cluster_transition_host import DockerZk
except ModuleNotFoundError:
    from md_cluster_transition_host import DockerZk


READY = re.compile(r"TRADE_PARTITION_READY node:([^,]+), partition:(P[0-9]{3}), epoch:([0-9]+), committedStateSeq:([0-9]+)")
FAILED = re.compile(r"TRADE_PARTITION_RECOVERY_FAILED node:([^,]+), partition:(P[0-9]{3}), epoch:([0-9]+)")
NODES = {"TradeSvrA": "dc-saas-tradesvr", "TradeSvrB": "dc-saas-tradesvr-b"}


def timestamp(value):
    # Python 3.9 accepts microseconds, while Docker timestamps use nanoseconds.
    value = re.sub(r"(\.[0-9]{6})[0-9]+", r"\1", value)
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def summarize_readiness(text, node, started_at, assignments):
    started = timestamp(started_at)
    ready = {}
    failures = Counter()
    oom = 0
    # stdout/stderr may have been captured separately; their concatenation is
    # not chronological. Docker's ISO timestamps sort lexically within a run.
    for line in sorted(text.splitlines()):
        try:
            at = timestamp(line.split(" ", 1)[0])
        except (ValueError, IndexError):
            continue
        if at < started:
            continue
        if "OutOfMemoryError" in line:
            oom += 1
        match = READY.search(line)
        if match and match[1] == node:
            ready[(match[2], int(match[3]))] = (at, int(match[4]))
        match = FAILED.search(line)
        if match and match[1] == node:
            key = (match[2], int(match[3]))
            failures[match[2]] += 1
            ready.pop(key, None)
    required = [row for row in assignments if row.get("primary") == node
                and row.get("state") in ("READY", "ACTIVE")]
    missing = []
    times = []
    for row in required:
        evidence = ready.get((row["partitionId"], int(row["epoch"])))
        if evidence is None:
            missing.append(row["partitionId"])
        else:
            at, seq = evidence
            times.append({"partitionId": row["partitionId"], "epoch": int(row["epoch"]),
                          "readyAtUtc": at.isoformat(), "secondsFromContainerStart": round((at - started).total_seconds(), 3),
                          "committedStateSeq": seq})
    times.sort(key=lambda row: row["secondsFromContainerStart"], reverse=True)
    return {"assignedPrimaryCount": len(required), "readyEvidenceCount": len(times),
            "missingReadyEvidence": sorted(missing), "recoveryFailureCounts": dict(failures),
            "oomLogCount": oom, "lastReadySecondsFromStart": times[0]["secondsFromContainerStart"] if times else None,
            "slowestReadyPartitions": times[:10], "businessWritableVerified": False}


def run(command, timeout=30):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Docker/Java logs may contain credentials: no raw output on failure.
        raise RuntimeError("Read-only observer command failed: " + command[0])
    return result.stdout


def inspect_node(node, assignments):
    container = NODES[node]
    inspected = json.loads(run(["docker", "inspect", container]))[0]
    state = inspected["State"]
    started_at = state["StartedAt"]
    # docker logs writes some log lines to stderr. Collect both without exposing
    # or storing raw logs (unlike diagnostic log dumps).
    log_result = subprocess.run(["docker", "logs", "--timestamps", "--since", started_at, container],
                                capture_output=True, text=True, timeout=60)
    if log_result.returncode:
        raise RuntimeError("Cannot read current-process recovery evidence")
    logs = log_result.stdout + "\n" + log_result.stderr
    report = summarize_readiness(logs, node, started_at, assignments)
    report.update({"container": container, "running": state["Running"], "imageId": inspected["Image"],
                   "startedAtUtc": started_at, "restartCount": inspected["RestartCount"],
                   "cgroupOomKilled": state["OOMKilled"], "memoryLimitBytes": inspected["HostConfig"]["Memory"],
                   "cpuLimit": inspected["HostConfig"].get("NanoCpus", 0) / 1e9})
    if state["Running"]:
        config = run(["docker", "exec", container, "sh", "-c",
                      "grep '^trade.cluster.snapshot.periodic.' config/application.properties || true"])
        report["periodicSnapshotConfig"] = dict(line.split("=", 1) for line in config.splitlines() if "=" in line)
        root = "/srv/dc/data/" + node
        sizes = run(["docker", "exec", container, "du", "-sk", root + "/journal", root + "/snapshot"])
        report["directoryKiB"] = {line.split()[1].rsplit("/", 1)[1]: int(line.split()[0]) for line in sizes.splitlines()}
        files = run(["docker", "exec", container, "find", root + "/snapshot", "-type", "f", "-name", "latest.json"])
        report["snapshotPartitionCount"] = len(files.splitlines())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--zk-container", default="dc-saas-zookeeper")
    parser.add_argument("--zk-server", default="127.0.0.1:32181")
    parser.add_argument("--partitions", type=int, default=256)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.partitions < 1 or args.partitions > 256:
        raise ValueError("partitions must be between 1 and 256")
    zk = DockerZk(args.zk_container, args.zk_server, "/dc/cluster/tradesvr/partitions", "docker")
    rows = [record["value"] for record in zk.read_all(args.partitions)]
    report = {"generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(), "readOnly": True,
              "scope": "current-process recovery baseline; no injected failure; no RPO/business verification",
              "assignmentCount": len(rows), "assignmentStates": dict(Counter(row.get("state") for row in rows)),
              "legacyAssignmentMetadataCount": sum(int(row.get("protocolVersion", 0)) < 3
                                                   or int(row.get("assignmentVersion", 0)) <= 0 for row in rows),
              "nodes": {node: inspect_node(node, rows) for node in NODES}}
    after = [record["value"] for record in zk.read_all(args.partitions)]
    report["assignmentsUnchangedDuringObservation"] = rows == after
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for node, item in report["nodes"].items():
        print(node + ": READY evidence=" + str(item["readyEvidenceCount"]) + "/" + str(item["assignedPrimaryCount"])
              + " startupToLastReadySeconds=" + str(item["lastReadySecondsFromStart"])
              + " snapshots=" + str(item.get("snapshotPartitionCount")))
    print("read_only=true failure_injected=false business_verified=false output=" + args.output)


if __name__ == "__main__":
    main()
