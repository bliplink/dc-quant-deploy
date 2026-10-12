#!/usr/bin/env python3
"""Bounded, read-only WAL archive inventory; never authorizes deletion.

Report allocated blocks (st_blocks) AND apparent file sizes because Chronicle
preallocates sparse .cq4 files. An old timestamp is NOT proof of retireability.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import stat
import time

NODES = ("OrderSvrA", "OrderSvrB", "OrderSvrC", "TradeSvrA", "TradeSvrB")
ARCHIVE_NAME = re.compile(r"^(P[0-9]{3})-epoch([0-9]+)-seq([0-9]+)-([0-9]+)$")


def inventory(data_root: Path, now_millis: int, retention_millis: int,
              max_segments: int = 2048) -> dict:
    if not data_root.is_dir() or data_root.is_symlink():
        raise ValueError("unsafe data root; must be real directory")
    if retention_millis <= 0 or max_segments < 1:
        raise ValueError("invalid read-only archive bounds")
    report = {
        "schema": "dc-saas-wal-archive-inventory-v1",
        "generatedUtc": datetime.fromtimestamp(now_millis / 1000, timezone.utc).isoformat(),
        "readOnly": True,
        "retentionMillis": retention_millis,
        "serviceNodes": [],
        "summary": {"archiveDirectories": 0, "agedCandidateDirectories": 0,
                    "archiveAllocatedBytes": 0, "activeAllocatedBytes": 0,
                    "unsafeOrUnknownEntries": 0, "deletionAuthorized": 0},
        "deletionStatus": "DISABLED_NO_SIGNED_SNAPSHOT_REPLICA_PROJECTION_ACK_PROOFS"
    }
    for name in NODES:
        journal = data_root / name / "journal"
        if journal.is_symlink() or not journal.is_dir():
            raise ValueError("unsafe/missing live journal directory for " + name)
        active = 0
        archive_bytes = 0
        total = 0
        aged = 0
        anomalies = []
        archive_root = journal / ".archive"
        for part in journal.iterdir():
            if part.name == ".archive":
                continue
            if part.is_symlink():
                anomalies.append("SYMLINK_IN_ACTIVE_PARTITION:" + part.name)
                continue
            if not re.fullmatch(r"P[0-9]{3}", part.name):
                continue
            if not part.is_dir():
                anomalies.append("INVALID_ACTIVE_PARTITION:" + part.name)
                continue
            for item in part.iterdir():
                if item.is_symlink():
                    anomalies.append("SYMLINK_IN_ACTIVE_WAL:" + item.name)
                elif item.is_file():
                    active += item.stat().st_blocks * 512
        if archive_root.is_symlink():
            raise ValueError("symlink archive root for " + name)
        if archive_root.exists():
            if not archive_root.is_dir():
                raise ValueError("archive root is not a directory for " + name)
            segments = sorted(archive_root.iterdir(), key=lambda p: p.name)
            if len(segments) > max_segments:
                raise ValueError("archive scan bound exceeded for " + name)
            for item in segments:
                if item.is_symlink() or not item.is_dir():
                    anomalies.append("UNSAFE_ARCHIVE_ENTRY:" + item.name)
                    continue
                match = ARCHIVE_NAME.fullmatch(item.name)
                if match is None:
                    anomalies.append("UNKNOWN_ARCHIVE_ID:" + item.name)
                    continue
                closed_at = int(match.group(4))
                partition = match.group(1)
                epoch = int(match.group(2))
                through = int(match.group(3))
                if (closed_at < 0 or closed_at > now_millis or
                        epoch < 0 or through < 0):
                    anomalies.append("INVALID_ARCHIVE_BOUNDARY:" + item.name)
                    continue
                segment_bytes = 0
                for child in item.iterdir():
                    if child.is_symlink() or not child.is_file():
                        anomalies.append("UNSAFE_ARCHIVE_CONTENT:" + item.name)
                    else:
                        segment_bytes += child.stat().st_blocks * 512
                archive_bytes += segment_bytes
                total += 1
                if now_millis - closed_at >= retention_millis:
                    aged += 1
        node = {"name": name, "activeAllocatedBytes": active,
                "archiveAllocatedBytes": archive_bytes,
                "archiveDirectories": total, "agedCandidateDirectories": aged,
                "unsafeOrUnknownEntries": anomalies,
                "retireAllowed": False,
                "retireBlockedReasons": [
                    "NO_VERIFIED_ARCHIVE_SEAL_AND_DURABLE_LEDGER",
                    "NO_SIGNED_FULL_SNAPSHOT_AT_ARCHIVE_BOUNDARY",
                    "NO_ALL_REQUIRED_REPLICA_RESTORABLE_IMAGE_WATERMARKS",
                    "NO_PROJECTION_AND_OTHER_CONSUMER_DURABLE_WATERMARKS",
                    "NO_CLOSED_READER_AND_ROLLBACK_HISTORY_FENCE",
                ]}
        report["serviceNodes"].append(node)
        report["summary"]["archiveDirectories"] += total
        report["summary"]["agedCandidateDirectories"] += aged
        report["summary"]["archiveAllocatedBytes"] += archive_bytes
        report["summary"]["activeAllocatedBytes"] += active
        report["summary"]["unsafeOrUnknownEntries"] += len(anomalies)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--retention-hours", type=int, default=48)
    p.add_argument("--max-segments-per-service", type=int, default=2048)
    p.add_argument("--output", type=Path)
    a=p.parse_args()
    if a.retention_hours < 1:
        raise SystemExit("invalid retention hours")
    result=inventory(a.data_root,int(time.time()*1000),
                     a.retention_hours*3600*1000,
                     a.max_segments_per_service)
    value=json.dumps(result,indent=2,sort_keys=True)
    if a.output:
        if a.output.exists() or a.output.is_symlink():
            raise SystemExit("refuse to overwrite existing inventory")
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(value+"\n")
    print(value)


if __name__=="__main__":
    main()
