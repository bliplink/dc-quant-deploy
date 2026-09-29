#!/usr/bin/env python3
"""Bounded, network-isolated Trade snapshot lab on an already copied Colima journal.

Never mounts live data, modifies assignments, starts the service, or logs raw journal payloads.
Temporary containers are removed; copied input and fresh output directories are retained.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import hashlib
import re
import subprocess
import time
import uuid
from pathlib import Path

LAB_BASE = "/data/dc-saas-isolated-labs"
SAFE_PARTITION = re.compile(r"P[0-9]{3}\Z")
SAFE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def helper_fingerprint(test_classes):
    folder = (Path(test_classes) / "com/app/dc/service/cluster").resolve()
    files = sorted(path for path in folder.glob("TradeSnapshotOfflineLab*.class")
                   if path.name == "TradeSnapshotOfflineLab.class" or path.name.startswith("TradeSnapshotOfflineLab$"))
    if not files or len(files) > 64 or sum(path.stat().st_size for path in files) > 8 * 1024 * 1024:
        raise ValueError("offline helper class budget exceeded or missing")
    digest = hashlib.sha256()
    for path in files:
        if path.resolve().parent != folder:
            raise ValueError("offline helper class escaped its folder")
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run(command, timeout=30, check=True):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # Do not emit arbitrary tool output: copied journals contain business state.
        raise RuntimeError("isolated lab command failed: " + command[0])
    return result


def validate(args):
    capture_trials = getattr(args, "capture_trials", 1)
    if not 1 <= capture_trials <= 5 or (capture_trials > 1 and (not args.resident or getattr(args, "mode", "recovery") != "recovery")):
        raise ValueError("capture profiling supports at most five trials with an explicit resident partition")
    if getattr(args, "mode", "recovery") not in ("recovery", "order-history-audit"):
        raise ValueError("unsupported lab mode")
    if getattr(args, "mode", "recovery") == "order-history-audit" and args.resident:
        raise ValueError("order history audit supports one copied partition per run")
    if not SAFE_DIGEST.fullmatch(args.image):
        raise ValueError("image must be a pinned local sha256 image ID")
    if not SAFE_PARTITION.fullmatch(args.partition) or int(args.partition[1:]) >= 256:
        raise ValueError("invalid partition")
    if args.resident and (not SAFE_PARTITION.fullmatch(args.resident) or int(args.resident[1:]) >= 256 or args.resident == args.partition):
        raise ValueError("invalid resident partition")
    if not 128 <= args.heap_mib <= 1024 or not args.heap_mib + 256 <= args.memory_mib <= 2048:
        raise ValueError("heap/container memory exceeds the isolated lab budget")
    if not 30 <= args.timeout_seconds <= 600 or not 1 <= args.delta_batches <= 10000:
        raise ValueError("invalid time/delta budget")
    path = Path(args.journal_copy_root)
    if not path.is_absolute() or ".." in path.parts or not str(path).startswith(LAB_BASE + "/") or path.name != "journal":
        raise ValueError("journal must be an isolated copy under " + LAB_BASE)
    test_class = Path(args.test_classes) / "com/app/dc/service/cluster/TradeSnapshotOfflineLab.class"
    if not test_class.is_file():
        raise ValueError("compiled offline lab class is required")
    if Path(args.output).exists():
        raise ValueError("refusing to overwrite an existing evidence file")


def execute(args):
    validate(args)
    helper_sha = helper_fingerprint(args.test_classes)
    journal = run(["colima", "ssh", "--", "sudo", "-n", "readlink", "-f", args.journal_copy_root]).stdout.strip()
    if journal != str(Path(args.journal_copy_root)) or not journal.startswith(LAB_BASE + "/"):
        raise ValueError("journal copy canonical path escaped or changed")
    run(["colima", "ssh", "--", "sudo", "-n", "test", "-f", str(Path(journal).parent / "ISOLATED_LAB")])
    for partition in [args.partition] + ([args.resident] if args.resident else []):
        actual = run(["colima", "ssh", "--", "sudo", "-n", "readlink", "-f", journal + "/" + partition]).stdout.strip()
        if actual != journal + "/" + partition:
            raise ValueError("copied partition resolves outside isolated journal")
        run(["colima", "ssh", "--", "sudo", "-n", "test", "-f", actual + "/metadata.cq4t"])

    run(["docker", "image", "inspect", "--format", "{{.Id}}", args.image])
    marker = Path(__file__).resolve().parent / "fixtures/trade-snapshot-lab/ISOLATED_LAB"
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    created = run(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--memory", "128m",
                   "--cpus", "1", "--mount", "type=bind,src=" + LAB_BASE + ",dst=/labs",
                   "--mount", "type=bind,src=" + str(marker) + ",dst=/marker,readonly",
                   "--entrypoint", "sh", args.image, "-c",
                   'set -eu; task_lab=$(mktemp -d /labs/trade-snapshot-run.XXXXXXXX); '
                   'cp /marker "$task_lab/ISOLATED_LAB"; printf "%s\\n" "$task_lab"']).stdout.strip()
    if not re.fullmatch(r"/labs/trade-snapshot-run\.[A-Za-z0-9]+", created):
        raise RuntimeError("unexpected isolated output directory")
    lab_root = LAB_BASE + created[len("/labs"):]
    name = "dc-trade-offline-lab-" + uuid.uuid4().hex[:12]
    command = ["docker", "create", "--name", name, "--pull", "never", "--network", "none",
               "--memory", str(args.memory_mib) + "m", "--cpus", "1",
               "--mount", "type=bind,src=" + lab_root + ",dst=/lab",
               "--mount", "type=bind,src=" + journal + ",dst=/lab/journal",
               "--mount", "type=bind,src=" + str(Path(args.test_classes).resolve()) + ",dst=/probe/classes,readonly",
               "--entrypoint", "java", args.image, "-Xms128m", "-Xmx" + str(args.heap_mib) + "m",
               "-Xmn" + str(args.heap_mib // 4) + "m", "-XX:MaxDirectMemorySize=128m", "-cp",
               "classes:lib/*:/probe/classes", "com.app.dc.service.cluster.TradeSnapshotOfflineLab"]
    if getattr(args, "mode", "recovery") == "order-history-audit":
        command.extend(["--audit-order-history", "/lab", args.partition])
    else:
        command.extend(["/lab", args.partition, str(args.delta_batches)])
        if args.resident:
            command.append(args.resident)
            if getattr(args, "capture_trials", 1) > 1:
                command.append(str(args.capture_trials))
    report = {"generatedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "scope": "isolated copied journal; no live failover/business verification",
              "imageId": args.image, "heapMiB": args.heap_mib, "memoryMiB": args.memory_mib,
              "cpus": 1, "timeoutSeconds": args.timeout_seconds, "journalCopyRoot": journal,
              "mode": getattr(args, "mode", "recovery"),
              "captureTrials": getattr(args, "capture_trials", 1),
              "helperClassesSha256AtLaunch": helper_sha,
              "retainedLabOutputRoot": lab_root, "partition": args.partition, "residentPartition": args.resident}
    run(command)
    timed_out = False
    started = time.monotonic()
    try:
        run(["docker", "start", name])
        next_notice = started
        while True:
            state = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", name]).stdout)
            elapsed = time.monotonic() - started
            if not state["Running"]:
                break
            if elapsed >= args.timeout_seconds:
                timed_out = True
                run(["docker", "stop", "--timeout", "5", name], timeout=15)
                state = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", name]).stdout)
                break
            if time.monotonic() >= next_notice:
                print("LAB_WATCH partition=" + args.partition + " elapsedSeconds=" + str(int(elapsed)), flush=True)
                next_notice = time.monotonic() + 20
            time.sleep(2)
        report.update({"elapsedSeconds": round(time.monotonic() - started, 3), "exitCode": state["ExitCode"],
                       "cgroupOomKilled": state["OOMKilled"], "timedOut": timed_out})
        probe_file = output.with_name(output.name + ".probe.tmp")
        if probe_file.exists():
            raise ValueError("temporary evidence target already exists")
        copied = run(["docker", "cp", name + ":/lab/result.json", str(probe_file)], check=False)
        if copied.returncode == 0:
            report["probe"] = json.loads(probe_file.read_text(encoding="utf-8"))
            probe_file.unlink()  # Only this newly generated exact temporary evidence path.
        if timed_out:
            report["outcome"] = "TIMEOUT"
        elif state["OOMKilled"]:
            report["outcome"] = "CGROUP_OOM"
        elif state["ExitCode"] == 0 and report.get("probe", {}).get("outcome") == "PASS":
            report["outcome"] = "PASS"
        else:
            report["outcome"] = "FAILED"
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("LAB_RESULT outcome=" + report["outcome"] + " output=" + str(output), flush=True)
        print("LAB_RETAINED outputRoot=" + lab_root + " inputCopyUnremoved=true", flush=True)
    finally:
        # Never touch service containers or remove the copied journal/output directories.
        current = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", name]).stdout)
        if current["Running"]:
            run(["docker", "stop", "--timeout", "5", name], timeout=15)
        run(["docker", "rm", name])
    return 0 if report["outcome"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--image", required=True)
    parser.add_argument("--journal-copy-root", required=True)
    parser.add_argument("--test-classes", required=True)
    parser.add_argument("--partition", default="P204")
    parser.add_argument("--resident")
    parser.add_argument("--capture-trials", type=int, default=1)
    parser.add_argument("--mode", choices=("recovery", "order-history-audit"), default="recovery")
    parser.add_argument("--heap-mib", type=int, default=768)
    parser.add_argument("--memory-mib", type=int, default=1536)
    parser.add_argument("--delta-batches", type=int, default=1000)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", required=True)
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
