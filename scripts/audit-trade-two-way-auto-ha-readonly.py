#!/usr/bin/env python3
"""Live Trade A/B two-direction failover preflight. Strictly READ ONLY.

Never writes ZK, publishes replica health, rewrites WAL, uses SIGKILL,
or grants READY. An ordinary ZK health field is not an independent
signed durable business/Projection attestation.
"""
import argparse
from collections import Counter
import datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from md_cluster_transition_host import DockerZk  # noqa
sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib.machinery import SourceFileLoader
legacy = SourceFileLoader(
    "previous_preflight",
    str(Path(__file__).resolve().parent / "check-trade-failback-preflight.py")
).load_module()

PARTITION_ROOT = "/dc/cluster/tradesvr/partitions"
NODES = {"TradeSvrA", "TradeSvrB"}


def inspect(assignments, health, runtime, now_ms):
    required = {"P%03d" % n for n in range(256)}
    if len(assignments) != 256 or {x["value"]["partitionId"] for x in assignments} != required:
        raise ValueError("partial or duplicate live ZK partition inventory")
    tally, reasons, samples = Counter(), Counter(), []
    blocked = 0
    for row in assignments:
        value = row["value"]
        partition = value["partitionId"]
        src = value.get("primary")
        target = value.get("replica")
        epoch = value.get("epoch")
        if src not in NODES or target not in NODES or src == target:
            raise ValueError("unrecognized primary or replica assignment")
        tally[src] += 1
        why = []
        if value.get("state") != "READY":
            why.append("ZK_NOT_READY")
        if not isinstance(epoch, int) or epoch < 1:
            why.append("INVALID_EPOCH")
        snapshot = runtime / "data" / target / "snapshot" / partition / "latest.json"
        local = None
        if not snapshot.is_file() or snapshot.is_symlink():
            why.append("RECIPIENT_LOCAL_SNAPSHOT_ABSENT")
        else:
            try:
                local = json.loads(snapshot.read_text())
                if local.get("partitionId") != partition or local.get("epoch") != epoch:
                    why.append("RECIPIENT_LOCAL_SNAPSHOT_STALE_EPOCH")
                if not isinstance(local.get("snapshotSeq"), int):
                    why.append("RECIPIENT_INVALID_SNAPSHOT_SEQ")
            except (OSError, ValueError):
                why.append("RECIPIENT_INVALID_SNAPSHOT")
        record = health.get(partition)
        if record is None:
            why.append("REPLICATION_HEALTH_MISSING")
        else:
            if any((record.get("primary") != src,
                    record.get("replica") != target,
                    record.get("epoch") != epoch,
                    record.get("partitionId") != partition)):
                why.append("HEALTH_ASSIGNMENT_MISMATCH")
            if record.get("degraded") is not False:
                why.append("HEALTH_DEGRADED")
            timestamp = record.get("updatedAt")
            if not isinstance(timestamp, int) or timestamp <= 0 or timestamp > now_ms:
                why.append("HEALTH_TIMESTAMP_INVALID")
            elif now_ms - timestamp > 60_000:
                why.append("HEALTH_STALE_OVER_ONE_MINUTE")
            if local is not None and isinstance(local.get("snapshotSeq"), int):
                if not isinstance(record.get("replicatedSeq"), int):
                    why.append("HEALTH_WATERMARK_INVALID")
                elif record["replicatedSeq"] < local["snapshotSeq"]:
                    why.append("HEALTH_BEHIND_RECIPIENT_SNAPSHOT")
        if why:
            blocked += 1
        for reason in why:
            reasons[reason] += 1
        if why and len(samples) < 12:
            samples.append({"partition": partition, "source": src, "replica": target,
                            "epoch": epoch, "blockers": why})
    return {
        "mode": "READ_ONLY_NON_AUTHORIZING",
        "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "primaryCounts": dict(tally),
        "healthRecordCount": len(health),
        "blockedPartitionCount": blocked,
        "blockerCounts": dict(reasons),
        "sample": samples,
        "safeToSigkillEitherPrimary": False,
        "mandatoryUnverified": [
            "FULL_SOURCE_COMMITTED_WAL_AND_RECEIVER_FSYNC",
            "INDEPENDENT_REPLICA_SIGNATURE_AND_BUSINESS_PROJECTION_RECONCILIATION",
            "TWO_DIRECTION_AUTOMATIC_RESTART_CATCHUP_PROVEN_IN_LIVE_FAULT",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", type=Path,
                   default=Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016"))
    p.add_argument("--zk-container", default="dc-saas-zookeeper")
    p.add_argument("--zk-server", default="127.0.0.1:32181")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    zk = DockerZk(args.zk_container, args.zk_server, PARTITION_ROOT, "docker")
    rows = zk.read_all(256)
    health = legacy.read_health(zk)
    result = inspect(rows, health, args.runtime, int(time.time() * 1000))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
