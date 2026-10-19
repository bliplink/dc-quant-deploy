#!/usr/bin/env python3
"""Read-only Trade snapshot/journal incident audit; never permits recovery or deletion.

Snapshots can be ahead of the Chronicle logical tail after a restart. Comparing
snapshotSeq only with baselineSeq is *not* sufficient: active .cq4 files normally
contain later records. This audit obtains actual logical tails from Trade's
recovery-failure log and reports the on-disk evidence without mutating WAL.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import mmap
from pathlib import Path
import re
import sys

FAILURE = re.compile(
    r"TradeSvr snapshot is ahead of local journal partition=(P\d{3}), "
    r"snapshotSeq=(\d+), localLastSeq=(\d+)"
)
ARCHIVE = re.compile(r"^(P\d{3})-epoch(\d+)-seq(\d+)-(\d+)$")
NODES = ("TradeSvrA", "TradeSvrB")


def _safe_file(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or unsafe evidence file: " + str(path))
    return path


def _baseline(path: Path):
    _safe_file(path)
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() in ("baselineSeq", "commitMarkerSeq",
                               "committedStateSeq", "epoch", "snapshotId"):
                result[key.strip()] = value.strip()
    for key in ("baselineSeq", "commitMarkerSeq", "committedStateSeq", "epoch"):
        if key not in result:
            raise ValueError("missing journal baseline field " + key)
        result[key] = int(result[key])
    return result


def _incidents(log_root: Path):
    result = {}
    for node in NODES:
        log = _safe_file(log_root / (node + ".log"))
        # Stream; logs can exceed 400 MiB. Capture only latest distinct failure.
        with log.open(encoding="utf-8", errors="replace") as src:
            for line in src:
                match = FAILURE.search(line)
                if match:
                    part, snap, tail = match.groups()
                    key = (node, part)
                    previous = result.get(key, {})
                    result[key] = {"node": node, "partition": part,
                                   "observedSnapshotSeq": int(snap),
                                   "observedLocalLastSeq": int(tail),
                                   "errorLines": previous.get("errorLines", 0) + 1}
    return result


def _archive_metadata(root: Path, part: str):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("unsafe or missing archive directory")
    count, largest = 0, None
    for entry in root.iterdir():
        match = ARCHIVE.fullmatch(entry.name)
        if match is None or match.group(1) != part:
            continue
        if entry.is_symlink() or not entry.is_dir():
            raise ValueError("unsafe archive segment")
        count += 1
        v = int(match.group(3))
        largest = v if largest is None else max(largest, v)
    return {"count": count, "maxArchivedDirectoryTailSeq": largest}


def scan_raw_cq_markers(journal_dir: Path, partition: str, epoch: int,
                        baseline_seq: int, snapshot_seq: int, runtime_tail: int):
    """Diagnostic byte markers only; not valid Chronicle records or commits."""
    if journal_dir.is_symlink() or not journal_dir.is_dir():
        raise ValueError("unsafe journal directory")
    prefix = re.escape(base64.b64encode(partition.encode("ascii")))
    marker = re.compile(prefix + b"\t" + str(epoch).encode() + b"\t([0-9]{1,10})\t")
    found = set()
    files = 0
    for path in journal_dir.glob("*.cq4"):
        _safe_file(path)
        files += 1
        with path.open("rb") as stream:
            if path.stat().st_size == 0:
                continue
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw:
                found.update(int(match.group(1)) for match in marker.finditer(raw))
    end = max(found) if found else None
    holes = [seq for seq in range(baseline_seq + 1, (end or baseline_seq) + 1)
             if seq not in found][:8]
    return {"cq4Files": files, "matchingRecordMarkers": len(found),
            "maxRawRecordMarkerSeq": end, "rawPrefixGaps": holes,
            "snapshotBeyondMaxRawMarker": snapshot_seq - end if end is not None else None,
            "rawMarkersBeyondReportedRuntimeTail": sum(seq > runtime_tail for seq in found),
            "chronicleIndexVerified": False, "walRecordFramingAndCommitAuthenticated": False}


def audit(data_root: Path, log_root: Path, scan_cq_markers: bool = False):
    if data_root.is_symlink() or not data_root.is_dir():
        raise ValueError("unsafe data root")
    if log_root.is_symlink() or not log_root.is_dir():
        raise ValueError("unsafe log root")
    events = _incidents(log_root)
    rows = []
    for (node, part), row in sorted(events.items()):
        home = data_root / node
        snap_path = _safe_file(home / "snapshot" / part / "latest.json")
        # Parse one partition at a time; 20 MB images can be large.
        with snap_path.open(encoding="utf-8") as src:
            snap = json.load(src)
        if snap.get("partitionId") != part:
            raise ValueError("snapshot identity mismatch for " + part)
        b = _baseline(home / "journal" / part / "baseline.properties")
        disk_seq = snap["snapshotSeq"]
        if not isinstance(disk_seq, int) or disk_seq < 0:
            raise ValueError("invalid snapshot sequence")
        archive = _archive_metadata(home / "journal" / ".archive", part)
        raw_evidence = (scan_raw_cq_markers(home / "journal" / part,
                        part, int(snap["epoch"]), b["baselineSeq"], disk_seq,
                        row["observedLocalLastSeq"]) if scan_cq_markers else None)
        rows.append({**row,
                     "rawChronicleByteEvidence": raw_evidence,
                     "diskSnapshotSeq": disk_seq,
                     "diskCommittedStateSeq": snap.get("committedStateSeq"),
                     "diskSnapshotEpoch": snap.get("epoch"),
                     "diskSnapshotMtimeUtc": datetime.fromtimestamp(
                         snap_path.stat().st_mtime, timezone.utc).isoformat(),
                     "activeJournalBaseline": {k: b[k] for k in (
                         "baselineSeq", "commitMarkerSeq", "committedStateSeq", "epoch")},
                     "archiveDirectoryEvidence": archive,
                     "reportedTailGap": max(0, row["observedSnapshotSeq"]
                                            - row["observedLocalLastSeq"]),
                     "snapshotMatchesObservedFailure":
                         disk_seq == row["observedSnapshotSeq"],
                     "physicalCQContentsProven": False,
                     "sourceCommittedHeadAuthenticated": False,
                     "safeToInstallOrPromote": False})
    return {"schema": "otc-trade-snapshot-wal-forensics-v1",
            "readOnly": True,
            "capturedUtc": datetime.now(timezone.utc).isoformat(),
            "incidentPartitions": len(rows),
            "totalReportedTailGap": sum(x["reportedTailGap"] for x in rows),
            "incidents": rows,
            "durableSourceHeadAndAckProof": "NOT_CHECKED",
            "chroniclePhysicalTailVerified": False,
            "recoveryAuthorized": False,
            "archiveDeletionAuthorized": False,
            "decision": "BLOCKED",
            "notice": "Chronicle baseline is not physical tail; neither a snapshot nor ZooKeeper READY authenticates committed HEAD."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--log-root", required=True, type=Path)
    parser.add_argument("--scan-cq-markers", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.data_root, args.log_root,
                       scan_cq_markers=args.scan_cq_markers)
        output = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("output exists or unsafe")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output)
        print(output)
        return 2
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("TRADE_FORENSICS_UNAVAILABLE: " + str(exc)[:250], file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
