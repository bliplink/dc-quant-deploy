#!/usr/bin/env python3
"""Read-only, per-partition forensic audit of elected-source Trade bootstrap.

No ZooKeeper writes, no Common READY, no synthetic ACK and no private keys.
An exact restored Snapshot is not a business/Projection health attestation.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def properties(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing, symlinked or incomplete file: {path}")
    result = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, val = line.split("=", 1)
            result[key.strip()] = val.strip()
    return result


def digest(content):
    return hashlib.sha256(content).hexdigest()


def check_partition(base, partition):
    left = base / "data" / "TradeSvrA" / "snapshot" / partition / "latest.json"
    right = base / "data" / "TradeSvrB" / "snapshot" / partition / "latest.json"
    ledger = (base / "data" / "TradeSvrB" / "certified-recipient" / partition
              / "install" / "ledger" / f"{partition}.recovery")
    baseline = (base / "data" / "TradeSvrB" / "journal" / partition
                / "baseline.properties")
    sealed = (base / "data" / "TradeSvrB" / "certified-recipient" / partition
              / "cross-epoch-old-tail")
    if not sealed.is_dir() or sealed.is_symlink():
        raise ValueError("old Epoch original physical evidence is absent")
    if not left.is_file() or not right.is_file() or left.is_symlink() or right.is_symlink():
        raise ValueError("source or recipient Snapshot absent or symlinked")
    a, b = left.read_bytes(), right.read_bytes()
    if len(a) == 0 or a != b:
        raise ValueError("source and replica exact Snapshot bytes differ")
    source = json.loads(a)
    target = json.loads(b)
    if source != target:
        raise ValueError("source and replica business object mismatch")
    for label, item in [("source", source), ("replica", target)]:
        if item.get("partitionId") != partition or item.get("epoch") != 2:
            raise ValueError(f"{label} wrong source partition / epoch")
        if item.get("snapshotSeq") != 0 or item.get("committedStateSeq") != 0:
            raise ValueError(f"{label} no longer zero committed boundary")
        for key in ("locations", "balances", "positions", "accountConfigs",
                    "symbolParas", "openOrders"):
            if item.get(key) != []:
                raise ValueError(f"{label} real business data present: {key}")
        dedupe = item.get("executionDedupe")
        if not isinstance(dedupe, dict) or any(dedupe.get(k) != []
               for k in ("applied", "terminalOrders")):
            raise ValueError(f"{label} execution dedupe not empty")
    l, j = properties(ledger), properties(baseline)
    for key, val in {
        "partition": partition, "phase": "REPLAY_COMPLETE", "epoch": "2",
        "headEpoch": "2", "snapshotSeq": "0", "headSeq": "0",
        "sourceStateSeq": "0", "sourceMarkerSeq": "0", "replaySeq": "0",
        "sha256": digest(a),
    }.items():
        if l.get(key) != val:
            raise ValueError(f"Common ledger invalid {key}: {l.get(key)}")
    for key, val in {
        "epoch": "2", "baselineSeq": "0", "committedStateSeq": "0",
        "committedStateEpoch": "0", "commitMarkerSeq": "0",
        "snapshotId": str(target.get("snapshotId")),
    }.items():
        if j.get(key) != val:
            raise ValueError(f"physical Chronicle baseline mismatch {key}: {j.get(key)}")
    return len(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runtime", type=Path)
    args = ap.parse_args()
    base = args.runtime.resolve()
    valid, failures, snapshot_bytes = 0, [], 0
    for slot in range(1, 256, 2):
        partition = f"P{slot:03d}"
        try:
            snapshot_bytes += check_partition(base, partition)
            valid += 1
        except (ValueError, OSError, json.JSONDecodeError) as error:
            failures.append((partition, str(error)))
    print(f"TRADE_REAL_E2_COMMON_INSTALL_SNAPSHOT_AUDIT exact={valid}/128 "
          f"bad={len(failures)} imageBytes={snapshot_bytes} "
          "sourceSnapshotEqual=true_if_exact_128 "
          "replicaBusinessReady=NOT_PROVEN")
    for partition, message in failures[:25]:
        print(f"  BLOCKED {partition}: {message}")
    return 0 if valid == 128 and not failures else 1


if __name__ == "__main__":
    sys.exit(main())
