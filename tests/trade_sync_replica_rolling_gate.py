#!/usr/bin/env python3
"""Fail-closed preflight for Trade rolling releases while all durable replica
ACKs are required. Read-only ZooKeeper evidence; never modifies assignments.

A 2-node Primary+Replica cluster with synchronous ACK to *every* configured
replica cannot tolerate an in-place restart of that replica. More replica nodes
do not change this until the replication commit policy itself uses a verified
quorum. Fail closed even for non-primary stops until proven safe.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any


def evaluate(assignments: list[dict[str, Any]], target: str, replication_required: bool,
             complete_catalog: bool) -> dict[str, Any]:
    if not re.fullmatch(r"TradeSvr[A-Za-z0-9]+", target) or not assignments:
        raise ValueError("need a concrete Trade node and nonempty authoritative assignments")
    seen: set[str] = set()
    blocked: list[dict[str, str]] = []
    for row in assignments:
        p = row.get("partitionId")
        primary = row.get("primary")
        replicas = row.get("replicas")
        if replicas is None:
            replicas = [row.get("replica")]
        if (not isinstance(p, str) or not re.fullmatch(r"P[0-9]{3}", p)
                or p in seen or not isinstance(primary, str)
                or not isinstance(replicas, list) or not replicas
                or any(not isinstance(n, str) or not n for n in replicas)
                or primary in replicas or row.get("state") != "READY"
                or int(row.get("epoch", 0)) <= 0):
            raise ValueError("unsafe/incomplete Trade assignment catalog")
        seen.add(p)
        if target == primary:
            blocked.append({"partition": p, "reason": "TARGET_IS_PRIMARY"})
        elif target in replicas:
            blocked.append({
                "partition": p,
                "reason": ("ALL_REPLICA_ACKS_REQUIRED"
                           if replication_required else "UNPROVEN_REPLICA_DURABILITY")
            })
    # Even a clean partial listing can NEVER authorize a rolling restart.
    safe = not blocked and complete_catalog and len(seen) == 256
    return {
        "status": "PASS" if safe else "BLOCK" if blocked else "UNPROVEN",
        "targetNode": target,
        "checkedPartitions": len(seen),
        "completeCatalog": complete_catalog and len(seen) == 256,
        "allReplicaAcksRequired": replication_required,
        "blockingPartitions": blocked,
        "authorizesRollingRestart": safe,
    }


def parse_required_flag(path: str) -> bool:
    found: list[str] = []
    with open(path, encoding="utf-8") as source:
        for line in source:
            text = line.strip()
            if text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            if key.strip() == "trade.cluster.replication.required":
                found.append(value.strip().lower())
    if len(found) != 1 or found[0] not in ("true", "false"):
        raise ValueError("Trade strict replication policy missing or ambiguous")
    return found[0] == "true"


def fetch_zk(container: str, endpoint: str, partitions: list[str]) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", container):
        raise ValueError("unsafe ZooKeeper container")
    if not re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{1,4}", endpoint):
        raise ValueError("only local ZooKeeper permitted")
    if not partitions or len(set(partitions)) != len(partitions):
        raise ValueError("nonempty unique partition names required")
    if any(not re.fullmatch(r"P[0-9]{3}", p) for p in partitions):
        raise ValueError("invalid partition id")
    batch = "".join("get /dc/cluster/tradesvr/partitions/" + p + "\n"
                    for p in partitions) + "quit\n"
    done = subprocess.run([
        "docker", "exec", "-i", container,
        "/apache-zookeeper-3.8.4-bin/bin/zkCli.sh", "-server", endpoint,
    ], input=batch, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=55, check=True)
    result: dict[str, dict[str, Any]] = {}
    for line in done.stdout.splitlines():
        marker = line.find('{"')
        if marker < 0:
            continue
        try:
            row = json.loads(line[marker:])
        except json.JSONDecodeError:
            continue
        partition = row.get("partitionId")
        if partition in partitions:
            result[partition] = row
    if set(result) != set(partitions):
        raise ValueError("ZooKeeper did not return the complete requested Trade catalog")
    return [result[p] for p in partitions]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-node", required=True)
    parser.add_argument("--config", required=True, help="actual Primary Trade config")
    parser.add_argument("--zk-container", default="dc-saas-zookeeper")
    parser.add_argument("--zk-server", default="127.0.0.1:32181")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--partitions", help="comma-delimited known active partitions")
    group.add_argument("--all-256", action="store_true")
    args = parser.parse_args()
    try:
        parts = (["P%03d" % p for p in range(256)] if args.all_256
                 else args.partitions.split(","))
        rows = fetch_zk(args.zk_container, args.zk_server, parts)
        result = evaluate(rows, args.target_node,
                          parse_required_flag(args.config), args.all_256)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["authorizesRollingRestart"] else 2
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("TRADE_ROLLING_REPLICA_ACK_GATE_ERROR " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
