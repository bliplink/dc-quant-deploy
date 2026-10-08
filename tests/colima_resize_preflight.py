#!/usr/bin/env python3
"""Read-only, fail-closed preflight for a whole-Colima maintenance resize.

A successful preflight never starts/stops Colima. It is only one prerequisite
for a separately reviewed backup, quiesce, recovery and verification runbook.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

CRITICAL = ("OrderSvrA", "OrderSvrB", "OrderSvrC",
            "TradeSvrA", "TradeSvrB", "mysql", "clickhouse", "zookeeper")
IMPORTANT_CONTAINERS = ("dc-saas-ordersvr", "dc-saas-ordersvr-b",
                        "dc-saas-ordersvr-c", "dc-saas-tradesvr",
                        "dc-saas-tradesvr-b", "dc-saas-mysql",
                        "dc-saas-zookeeper", "dc-saas-robotsvr")


def issues_for_snapshot(s):
    """Evaluate provided evidence; missing evidence must never imply GO."""
    issues = []
    mandatory = ("host_cpu", "host_memory_gib", "target_cpu",
                 "target_memory_gib", "data_bytes", "backup_free_bytes",
                 "backup_separate_device", "running_critical_containers",
                 "robots_paused", "journal_consistency_verified",
                 "projection_consistency_verified", "restore_plan_verified")
    for key in mandatory:
        if key not in s:
            issues.append("missing evidence: " + key)
    if issues:
        return issues
    try:
        host_cpu = int(s["host_cpu"])
        host_memory = int(s["host_memory_gib"])
        target_cpu = int(s["target_cpu"])
        target_memory = int(s["target_memory_gib"])
        bytes_used = int(s["data_bytes"])
        backup_free = int(s["backup_free_bytes"])
    except (TypeError, ValueError):
        return ["invalid numeric evidence"]
    if host_cpu < 2 or target_cpu < 1 or target_cpu > host_cpu - 1:
        issues.append("target CPU leaves less than one host core free")
    if host_memory < 6 or target_memory < 2 or target_memory > host_memory - 4:
        issues.append("target RAM leaves less than 4 GiB for host macOS")
    if bytes_used <= 0:
        issues.append("critical persisted data size is missing")
    if not s["backup_separate_device"]:
        issues.append("no independent backup volume detected")
    if backup_free < (bytes_used * 6 // 5):
        issues.append("backup volume lacks 20% headroom above critical data size")
    running = s["running_critical_containers"]
    if not isinstance(running, list) or running:
        issues.append("critical containers not cleanly quiesced or evidence unavailable")
    for flag, reason in (("robots_paused", "Robot traffic not safely stopped"),
                         ("journal_consistency_verified", "Order/Trade journal commit and replica proof missing"),
                         ("projection_consistency_verified", "Projection authoritative consistency proof missing"),
                         ("restore_plan_verified", "tested restoration and rollback plan missing")):
        if s[flag] is not True:
            issues.append(reason)
    return issues


def run(cmd, timeout=20):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError("%s failed: %s" % (cmd[0], result.stderr[:250]))
    return result.stdout


def live_snapshot(target_cpu, target_memory, data_root, backup_root):
    out = run(["colima", "list"])
    profile = next((line.split() for line in out.splitlines()
                    if line.strip().startswith("default ")), [])
    if len(profile) < 6 or profile[1] != "Running":
        raise RuntimeError("Colima default running profile unavailable")
    host_cpu = int(run(["sysctl", "-n", "hw.logicalcpu"]).strip())
    ram = int(run(["sysctl", "-n", "hw.memsize"]).strip()) // (1024 ** 3)
    data_root = Path(data_root).expanduser()
    backup_root = Path(backup_root).expanduser()
    size = 0
    for name in CRITICAL:
        path = data_root / name
        if not path.is_dir():
            raise RuntimeError("missing critical persisted data: " + name)
        out = run(["du", "-sk", str(path)], timeout=35)
        size += int(out.split()[0]) * 1024
    separate = False
    free = 0
    if backup_root.is_dir():
        separate = os.stat(data_root).st_dev != os.stat(backup_root).st_dev
        st = os.statvfs(backup_root)
        free = st.f_bavail * st.f_frsize
    existing = run(["docker", "ps", "--format", "{{.Names}}"])
    running = sorted(set(existing.splitlines()).intersection(IMPORTANT_CONTAINERS))
    return {"host_cpu": host_cpu, "host_memory_gib": ram,
            "target_cpu": target_cpu, "target_memory_gib": target_memory,
            "data_bytes": size, "backup_free_bytes": free,
            "backup_separate_device": separate,
            "running_critical_containers": running, "robots_paused": False,
            "journal_consistency_verified": False,
            "projection_consistency_verified": False,
            "restore_plan_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", help="offline JSON snapshot for CI tests")
    parser.add_argument("--target-cpu", type=int, default=9)
    parser.add_argument("--target-memory-gib", type=int, default=18)
    parser.add_argument("--data-root", default="~/.opentradingcore/dc-saas-runtime-fresh2-20261005/data")
    parser.add_argument("--backup-root", default="/Volumes/OTC-Backup")
    args = parser.parse_args()
    try:
        if args.snapshot:
            with open(args.snapshot, encoding="utf-8") as f:
                snap = json.load(f)
        else:
            snap = live_snapshot(args.target_cpu, args.target_memory_gib,
                                 args.data_root, args.backup_root)
        issues = issues_for_snapshot(snap)
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        issues = ["unverified preflight evidence: " + str(exc)]
        snap = {}
    print("COLIMA_RESIZE_" + ("NO_GO" if issues else "PRECHECK_PASS"))
    if snap:
        print("host=%s CPU/%s GiB target=%s CPU/%s GiB persisted=%.2f GiB backup_free=%.2f GiB" %
              (snap.get("host_cpu"), snap.get("host_memory_gib"),
               snap.get("target_cpu"), snap.get("target_memory_gib"),
               float(snap.get("data_bytes", 0)) / 1024**3,
               float(snap.get("backup_free_bytes", 0)) / 1024**3))
    for issue in issues:
        print(" - " + issue)
    if not issues:
        print("This is NOT authorization to stop Colima: perform operator-reviewed maintenance separately.")
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
