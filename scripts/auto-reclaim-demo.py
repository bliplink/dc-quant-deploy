#!/usr/bin/env python3
"""OpenTradingCore calendar-retention janitor. Opt-in; NEVER prunes active WAL.

Two narrowly-defined classes may be reclaimed:
  1. rotated human-readable service logs under runtime/log
  2. metadata-only bootstrap Chronicle archives epoch0-seq0, and ONLY
     if confirmed no process has the metadata file open.

Real Order/Trade CQ .cq4 archives are NEVER eligible here. They require a
separate proof-bearing replica/Projection/restore contract. GC must fail closed.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ARCHIVE_NAME = re.compile(r"^P[0-9]{3}-epoch0-seq0-[0-9]+$")
ROTATED = re.compile(r"^[A-Za-z0-9_.-]+\.log\.[0-9]{4}-[0-9]{2}-[0-9]{2}(?:\.[0-9]+)?(?:\.gz)?$")
NODES = ("OrderSvrA", "OrderSvrB", "OrderSvrC")
DEFAULTS = {
    "enabled": False, "environment": "production",
    "rotatedLogRetentionDays": 3, "emptyBootstrapRetentionDays": 7,
    "maxDeletedBytesPerRun": 1073741824, "maxDeletedFilesPerRun": 100,
    "maxCandidatesPerRun": 150,
    "dryRun": False,
}

def load_config(path):
    obj = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(obj, dict):
        raise ValueError("configuration must be a JSON object")
    unknown = set(obj) - set(DEFAULTS)
    if unknown:
        raise ValueError("unknown config keys: " + ", ".join(sorted(unknown)))
    out = dict(DEFAULTS)
    out.update(obj)
    if type(out["enabled"]) is not bool or type(out["dryRun"]) is not bool:
        raise ValueError("enabled and dryRun must be booleans")
    if out["environment"] not in ("demo", "production"):
        raise ValueError("environment must be demo or production")
    for key in ("rotatedLogRetentionDays", "emptyBootstrapRetentionDays",
                "maxDeletedBytesPerRun", "maxDeletedFilesPerRun", "maxCandidatesPerRun"):
        if type(out[key]) is not int or out[key] <= 0:
            raise ValueError(key + " must be a positive integer")
    if out["rotatedLogRetentionDays"] < 2 or out["emptyBootstrapRetentionDays"] < 2:
        raise ValueError("must retain at least 2 days")
    if (out["maxDeletedBytesPerRun"] > 5 * 1024**3
            or out["maxDeletedFilesPerRun"] > 500
            or out["maxCandidatesPerRun"] > 500):
        raise ValueError("per-run delete budget is too high")
    # Production deliberately cannot opt into automatic deletion with the
    # demo policy; external retention controller must first supply proofs.
    if out["enabled"] and out["environment"] != "demo":
        raise ValueError("production reclaim requires a separate proof-bearing policy")
    return out

def classify_archive(path):
    """Return the metadata file only for an *exact* empty epoch0 queue."""
    if path.is_symlink() or not path.is_dir() or not ARCHIVE_NAME.fullmatch(path.name):
        return None
    try:
        entries = list(path.iterdir())
        if len(entries) != 1 or entries[0].name != "metadata.cq4t":
            return None
        file = entries[0]
        if file.is_symlink() or not file.is_file() or file.stat().st_size != 131072:
            return None
        return file
    except OSError:
        return None

def is_file_open(path, executable="lsof"):
    """Return None if unable to establish status; fail closed in that case."""
    try:
        completed = subprocess.run(
            [executable, "-nP", "--", str(path)], capture_output=True,
            text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 0:
        return True
    # lsof: rc=1 is 'no matching open files' only if it printed no error.
    if completed.returncode == 1 and not completed.stderr.strip():
        return False
    return None

def eligible_files(runtime, now, config):
    """Yield ('rotated_log'|'empty_bootstrap_archive', file, parent)."""
    log_root = runtime / "log"
    if log_root.is_dir() and not log_root.is_symlink():
        # Log directories may contain one level per service, but NEVER data/.
        folders = [log_root] + [x for x in log_root.iterdir()
                                 if x.is_dir() and not x.is_symlink()]
        for folder in folders:
            for file in folder.iterdir():
                if (not ROTATED.fullmatch(file.name) or file.is_symlink()
                        or not file.is_file()):
                    continue
                if now - file.stat().st_mtime >= config["rotatedLogRetentionDays"] * 86400:
                    yield ("rotated_log", file, None)
    data = runtime / "data"
    if data.is_dir() and not data.is_symlink():
        for node in NODES:
            archive_root = data / node / "journal" / ".archive"
            if not archive_root.is_dir() or archive_root.is_symlink():
                continue
            for folder in archive_root.iterdir():
                metadata = classify_archive(folder)
                if metadata is None:
                    continue
                if now - max(folder.stat().st_mtime, metadata.stat().st_mtime) >= (
                    config["emptyBootstrapRetentionDays"] * 86400
                ):
                    yield ("empty_bootstrap_archive", metadata, folder)

def safe_delete(file, parent, kind, open_probe):
    """Recheck class and inode before unlink. No active CQ, no data segment."""
    if file.is_symlink() or not file.is_file() or file.stat().st_nlink != 1:
        return False, "unsafe_file"
    before = file.stat()
    if kind == "empty_bootstrap_archive":
        if parent is None or classify_archive(parent) != file:
            return False, "archive_changed"
    elif not ROTATED.fullmatch(file.name):
        return False, "not_a_rotated_log"
    opened = open_probe(file)
    if opened is not False:
        return False, "open_or_unverifiable_file_handle"
    after = file.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        return False, "changed_during_check"
    try:
        file.unlink()
        if kind == "empty_bootstrap_archive":
            parent.rmdir()  # fails safe if any file appeared during deletion
        return True, None
    except OSError:
        return False, "unlink_failed"

def run_once(runtime, config, *, now=None, disk_reader=shutil.disk_usage,
             open_probe=is_file_open, delete_fn=safe_delete, candidate_cursor=0):
    """Reclaim only expired eligible files; never gate on disk usage."""
    if now is None:
        now = time.time()
    report = {
        "schema": "otc-demo-retention-status-v1",
        "checkedAtUtc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "enabled": config["enabled"], "environment": config["environment"],
        "dryRun": config["dryRun"], "deletedFiles": 0, "deletedBytes": 0,
        "policy": "RETENTION_DAYS_ONLY",
        "rotatedLogRetentionDays": config["rotatedLogRetentionDays"],
        "emptyBootstrapRetentionDays": config["emptyBootstrapRetentionDays"],
        "eligibleCandidates": 0, "blockedCandidates": 0, "blockedReasons": {},
        "nextCandidateCursor": 0, "totalExpiredCandidates": 0,
        "deletedByClass": {}, "warnings": [],
        "activeWALDeletionAllowed": False, "businessArchiveDeletionAllowed": False,
    }
    usage = disk_reader(runtime)
    report["usedPercentBefore"] = round(100 * usage.used / usage.total, 2)
    report["freeGiBBefore"] = round(usage.free / 1024**3, 2)
    if not config["enabled"]:
        report["decision"] = "DISABLED"
    else:
        report["decision"] = "DRY_RUN" if config["dryRun"] else "RETENTION_APPLIED"
        # A fixed first-N scan could forever starve the other partitions
        # when the first 150 CQ metadata files stay mapped by Colima.
        candidates = sorted(eligible_files(runtime, now, config),
                            key=lambda item: str(item[1]))
        count = len(candidates)
        report["totalExpiredCandidates"] = count
        start = max(0, candidate_cursor) % count if count else 0
        processed = 0
        for i in range(min(count, config["maxCandidatesPerRun"])):
            kind, file, parent = candidates[(start + i) % count]
            if report["deletedFiles"] >= config["maxDeletedFilesPerRun"]:
                report["warnings"].append("FILE_BUDGET_REACHED")
                break
            try:
                size = file.stat().st_size
            except OSError:
                report["blockedCandidates"] += 1
                report["blockedReasons"]["disappeared_during_scan"] = (
                    report["blockedReasons"].get("disappeared_during_scan", 0) + 1)
                processed += 1
                continue
            if report["deletedBytes"] + size > config["maxDeletedBytesPerRun"]:
                report["warnings"].append("BYTE_BUDGET_REACHED")
                break
            report["eligibleCandidates"] += 1
            processed += 1
            if config["dryRun"]:
                continue
            success, reason = delete_fn(file, parent, kind, open_probe)
            if success:
                report["deletedFiles"] += 1
                report["deletedBytes"] += size
                report["deletedByClass"][kind] = report["deletedByClass"].get(kind, 0) + 1
            else:
                report["blockedCandidates"] += 1
                report["blockedReasons"][reason] = report["blockedReasons"].get(reason, 0) + 1
        if count > config["maxCandidatesPerRun"]:
            report["warnings"].append("CANDIDATE_BUDGET_REACHED")
        report["nextCandidateCursor"] = (start + processed) % count if count else 0
    usage = disk_reader(runtime)
    report["usedPercentAfter"] = round(100 * usage.used / usage.total, 2)
    report["freeGiBAfter"] = round(usage.free / 1024**3, 2)
    # Disk metrics are advisory telemetry only, never a deletion threshold.
    if config["enabled"] and report["blockedCandidates"]:
        report["warnings"].append("EXPIRED_FILES_BLOCKED_BY_SAFETY_GUARDS")
    return report

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--status-path", required=True)
    args = parser.parse_args(argv)
    root = Path(args.runtime_root).expanduser().resolve(strict=True)
    if not root.is_dir() or not (root / "data").is_dir() or not (root / "log").is_dir():
        parser.error("runtime root must contain data/ and log/")
    config = load_config(args.config)
    status = Path(args.status_path).expanduser().absolute()
    if status.is_symlink() or root / "data" in status.parents or root / "log" in status.parents:
        parser.error("status must not overwrite runtime data or logs")
    status.parent.mkdir(parents=True, exist_ok=True)
    lockpath = status.with_suffix(status.suffix + ".lock")
    with lockpath.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("OTC_RETENTION_SKIPPED_ACTIVE_AGENT")
            return 0
        try:
            previous = json.loads(status.read_text(encoding="utf8")) if status.exists() else {}
            previous_cursor = int(previous.get("nextCandidateCursor", 0))
        except (ValueError, OSError, TypeError):
            previous_cursor = 0
        report = run_once(root, config, candidate_cursor=previous_cursor)
        tmp = status.with_name(status.name + ".tmp." + str(os.getpid()))
        try:
            with tmp.open("x", encoding="utf8") as f:
                json.dump(report, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, status)
        finally:
            if tmp.exists():
                tmp.unlink()
    print(json.dumps(report, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
