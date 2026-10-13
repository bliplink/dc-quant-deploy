#!/usr/bin/env python3
"""Fail-closed, READ-ONLY Trade replacement preflight.

Compare local full Trade Snapshot metadata for the source Primary and target
Replica. A replica with an older full snapshot may still have a complete WAL:
this script deliberately does NOT infer missing replica durability. It only
says whether the fast-snapshot-restore prerequisite is demonstrably absent.

The successful result is not permission to restart a Trade Primary: an actual
rollout still needs an authoritative same-epoch committed-HEAD/replica ACK and
an explicit failover rehearsal. No Docker, ZooKeeper or DB writes occur.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


class SnapshotEvidenceError(ValueError):
    pass


REQUIRED_SCALARS = ("partitionId", "snapshotId", "epoch", "snapshotSeq",
                    "committedStateSeq", "committedStateEpoch")
MAX_HEADER_BYTES = 65536


def read_metadata(snapshot_file: Path) -> dict:
    """Read only JSON's bounded initial metadata prefix, not 18 MB dedupe body."""
    with snapshot_file.open("rb") as stream:
        data = stream.read(MAX_HEADER_BYTES)
    text = data.decode("utf-8", "strict")
    result = {}
    for key in REQUIRED_SCALARS:
        match = re.search(r'"' + re.escape(key) + r'"\s*:\s*("[^"]*"|[0-9]+)', text)
        if not match:
            raise SnapshotEvidenceError(f"{snapshot_file}: missing {key} in bounded header")
        result[key] = json.loads(match.group(1))
    locations = re.search(r'"locations"\s*:\s*(\[[^\]]*\])', text)
    if not locations:
        raise SnapshotEvidenceError(f"{snapshot_file}: missing locations in bounded header")
    result["locations"] = json.loads(locations.group(1))
    if not isinstance(result["locations"], list):
        raise SnapshotEvidenceError("locations must be an array")
    if not isinstance(result["partitionId"], str) or not re.fullmatch(r"P[0-9]{3}", result["partitionId"]):
        raise SnapshotEvidenceError("invalid partition identity")
    if not isinstance(result["snapshotId"], str) or not result["snapshotId"]:
        raise SnapshotEvidenceError("missing snapshot identity")
    if result["epoch"] < 1 or result["snapshotSeq"] < result["committedStateSeq"]:
        raise SnapshotEvidenceError("invalid snapshot watermark")
    return result


def inspect(source: Path, target: Path, min_active: int) -> dict:
    if not source.is_dir() or not target.is_dir():
        raise SnapshotEvidenceError("both source and target snapshot roots must exist")
    active = []
    blocking = []
    for source_file in sorted(source.glob("P[0-9][0-9][0-9]/latest.json")):
        src = read_metadata(source_file)
        if src["partitionId"] != source_file.parent.name:
            raise SnapshotEvidenceError("source partition mismatched directory")
        if not src["locations"]:
            continue
        partition = src["partitionId"]
        active.append(partition)
        target_file = target / partition / "latest.json"
        if not target_file.is_file():
            blocking.append({"partition": partition, "reason": "target_snapshot_missing"})
            continue
        dst = read_metadata(target_file)
        if dst["partitionId"] != partition:
            blocking.append({"partition": partition, "reason": "target_snapshot_identity_mismatch"})
            continue
        # Snapshot sequence numbers are not comparable across epochs.
        if (dst["epoch"] != src["epoch"]
                or dst["committedStateEpoch"] != src["committedStateEpoch"]
                or src["committedStateEpoch"] != src["epoch"]):
            blocking.append({"partition": partition, "reason": "target_snapshot_epoch_mismatch",
                             "sourceEpoch": src["epoch"], "targetEpoch": dst["epoch"]})
            continue
        if (dst["committedStateSeq"] < src["committedStateSeq"]
                or dst["snapshotSeq"] < src["snapshotSeq"]):
            blocking.append({"partition": partition, "reason": "target_full_snapshot_behind",
                             "targetSnapshotSeq": dst["snapshotSeq"],
                             "sourceSnapshotSeq": src["snapshotSeq"]})
            continue
    if len(active) < min_active:
        raise SnapshotEvidenceError(
            f"not enough active snapshot partitions to prove scope: {len(active)} < {min_active}")
    return {
        "scope": "full-snapshot-only",
        "activePartitionCount": len(active),
        "blockedCount": len(blocking),
        "blocked": blocking,
        "fastSnapshotPreflight": "BLOCK" if blocking else "UNPROVEN",
        "authorizesPrimaryRestart": False,
        "walAndReplicaAckProof": "NOT_CHECKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-snapshots", type=Path, required=True)
    parser.add_argument("--target-snapshots", type=Path, required=True)
    parser.add_argument("--min-active", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.min_active <= 0:
        parser.error("--min-active must be positive")
    try:
        result = inspect(args.source_snapshots, args.target_snapshots, args.min_active)
    except (SnapshotEvidenceError, OSError, UnicodeError, json.JSONDecodeError) as error:
        result = {"fastSnapshotPreflight": "BLOCK", "error": str(error),
                  "authorizesPrimaryRestart": False}
    payload = json.dumps(result, indent=2, sort_keys=True)
    print(payload)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 2 if result["fastSnapshotPreflight"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
