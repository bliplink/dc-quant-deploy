#!/usr/bin/env python3
"""Measure actual Demo Tape fills from existing Order and Trade logs."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
from threading import Event, Thread


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
ROBOT = runpy.run_path(str(ROOT / "scripts/mac-demo-robot-traffic.py"))
DECODER = json.JSONDecoder()


def reports(line, offset):
    if offset < 0 or '"Terminal":"RobotSvr' not in line or '"ClOrdID":' not in line:
        return []
    try:
        payload, _ = DECODER.raw_decode(line[offset:])
    except ValueError:
        return []
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    return [payload] if isinstance(payload, dict) else []


def at(line):
    stamp = line.partition(" ")[0]
    stamp = re.sub(r"(\.\d{6})\d*Z$", r"\1+00:00", stamp).replace("Z", "+00:00")
    return datetime.fromisoformat(stamp)


def percentile(values, fraction):
    return round(values[math.ceil(len(values) * fraction) - 1], 3) if values else None


def voter_containers(generation, since, until):
    names = {}
    voter_name = re.compile(re.escape(generation) + r"-(order|trade)-[ab]-hostready(?:-retained-[a-z0-9_]+)?")
    output = subprocess.check_output(
        ["docker", "ps", "-a", "--no-trunc", "--filter", f"label=otc.mac.demo.generation={generation}",
         "--format", "{{.ID}} {{.Names}}"], text=True, timeout=20)
    for line in output.splitlines():
        ident, name = line.split()
        if voter_name.fullmatch(name):
            names[ident] = name
    if not names:
        raise RuntimeError("No physical Order or Trade voters found for this Demo generation")
    lifecycle = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Id}} {{.State.StartedAt}} {{.State.FinishedAt}}", *names],
        text=True, timeout=20)
    window = {"order": [], "trade": []}
    for line in lifecycle.splitlines():
        ident, started, finished = line.split()
        if started.startswith("0001-") or at(started) > until:
            continue
        if not finished.startswith("0001-") and at(finished) < since:
            continue
        window[voter_name.fullmatch(names[ident]).group(1)].append(ident)
    if not all(window.values()):
        raise RuntimeError("Missing physical Order or Trade logs for the sample window")
    current = [ident for ident, name in names.items() if name.endswith("-hostready")]
    return window, current


def resources(containers):
    stats = subprocess.check_output(["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers],
                                    text=True, timeout=30)
    keys = ("Name", "CPUPerc", "MemUsage", "MemPerc")
    samples = []
    for item in map(json.loads, stats.splitlines()):
        sample = {key: item[key] for key in keys}
        try:
            raw = subprocess.check_output(
                ["docker", "exec", item["Name"], "cat", "/sys/fs/cgroup/cpu.stat"],
                text=True, stderr=subprocess.DEVNULL, timeout=3)
            sample["cpu_cgroup_stat"] = {key: int(value) for key, value in map(str.split, raw.splitlines())}
            sample["cpu_cgroup_sampled_at"] = datetime.now(timezone.utc).isoformat()
        except (OSError, ValueError, subprocess.SubprocessError) as failure:
            sample["cpu_cgroup_error"] = type(failure).__name__
        samples.append(sample)
    return samples


@contextmanager
def sample_resources(generation):
    done = Event()
    samples = []

    def collect():
        voters = {f"{generation}-{service}-{slot}-hostready" for service in ("order", "trade") for slot in "ab"}
        names = voters | {"dc-saas-" + service for service in (
            "robotsvr", "gateway", "mysql", "zookeeper", "mdsvr", "projectionsvr",
            "apssvr", "loginsvr", "adminsvr", "managersvr", "liqsvr", "clickhouse",
        )}
        while not done.is_set():
            sample = {"at": datetime.now(timezone.utc).isoformat(),
                      "host_free_storage_bytes": shutil.disk_usage(ROOT).free}
            try:
                listing = subprocess.check_output(["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
                                                  text=True, timeout=15)
                selected = [ident for ident, name in map(str.split, listing.splitlines()) if name in names]
                if selected:
                    sample["containers"] = resources(selected)
                else:
                    sample["error"] = "No running containers in the Demo scope"
                sample["host_vm_stat"] = subprocess.check_output(["vm_stat"], text=True, timeout=5)
                sample["guest_pressure_memory_disk_stats"] = subprocess.check_output(
                    ["colima", "ssh", "--", "sh", "-c",
                     "for file in /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io "
                     "/proc/meminfo /proc/diskstats; do echo \"$file\"; cat \"$file\"; done"],
                    text=True, timeout=10)
                sample["guest_sampled_at"] = datetime.now(timezone.utc).isoformat()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                sample["error"] = type(exc).__name__
            samples.append(sample)
            done.wait(30)

    sampler = Thread(target=collect, name="mac-demo-resource-sampling")
    sampler.start()
    try:
        yield samples
    finally:
        done.set()
        sampler.join()


def measure(generation, since, until, locations=()):
    docker = ["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}',
              "dc-saas-gateway"]
    active = subprocess.check_output(docker, text=True, timeout=15).strip()
    if generation != active or not re.fullmatch(r"mac-demo-\d{8}-\d{6}", generation):
        raise RuntimeError("Expected the active Mac Demo generation")
    voters, current = voter_containers(generation, since, until)
    start, finish, quotes = {}, {}, set()
    for container in voters["trade"]:
        for line in ROBOT["logs"](container, since, until):
            if '"ExecType":"Newing"' not in line or "UpdateOrderHandler:" not in line:
                continue
            for report in reports(line, line.find("{", max(0, line.find("INFO sid:")))):
                key = (report.get("Location"), report.get("ClOrdID"))
                if not all(key) or (locations and key[0] not in locations) or report.get("ExecType") != "Newing":
                    continue
                if report.get("Terminal") == "RobotSvr" and report.get("Side") in {"Buy", "Sell"}:
                    quotes.add(key)
                elif report.get("Terminal") == "RobotSvr-Tape" and report.get("TimeInForce") == "IOC":
                    stamp = at(line)
                    start[key] = min(start.get(key, stamp), stamp)
    for container in voters["order"]:
        for line in ROBOT["logs"](container, since, until):
            if '"ExecType":"Trade"' not in line or '"OrdStatus":"Filled"' not in line:
                continue
            for report in reports(line, line.find("[{")):
                if (report.get("Terminal") != "RobotSvr-Tape" or report.get("ExecType") != "Trade"
                        or report.get("OrdStatus") != "Filled" or report.get("TimeInForce") != "IOC"
                        or not report.get("ExecID")):
                    continue
                key = (report.get("Location"), report.get("ClOrdID"))
                if all(key) and (not locations or key[0] in locations):
                    executions = finish.setdefault(key, {})
                    exec_id, stamp = report["ExecID"], at(line)
                    executions[exec_id] = min(executions.get(exec_id, stamp), stamp)
    samples = sorted((stamp - start[key]).total_seconds() * 1000
                     for key, executions in finish.items() if key in start
                     for stamp in executions.values() if stamp >= start[key])
    tape = sum(len(executions) for executions in finish.values())
    seconds = (until - since).total_seconds()
    tenants = {location for location, _ in quotes | set(start) | set(finish)}
    gaps = {location: [since, until] for location in (locations or tenants)}
    for (location, _), executions in finish.items():
        gaps[location].extend(executions.values())
    maximum_gaps = {}
    for location, timestamps in gaps.items():
        ordered = sorted(timestamps)
        maximum_gaps[location] = round(max((end - begin).total_seconds()
                                           for begin, end in zip(ordered, ordered[1:])), 3)
    return {"generation": generation, "from": since.isoformat(), "until": until.isoformat(),
            "measurement_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scope": "observed Robot activity and service-to-service Tape latency",
            "physical_log_containers": voters,
            "active_tenants_in_window": len(tenants),
            "quote_requests": len(quotes), "tape_requests": len(start), "filled_tape_executions": tape,
            "tape_requests_with_fill_in_window": len(set(start) & set(finish)),
            "tape_requests_without_fill_in_window": len(set(start) - set(finish)),
            "filled_tape_orders_without_ingress_in_window": len(set(finish) - set(start)),
            "filled_tape_executions_per_second": round(tape / seconds, 3),
            "largest_tape_fill_gap_seconds_by_tenant": maximum_gaps,
            "tape_trade_ingress_to_order_filled_publish_ms": {
                "paired_samples": len(samples), "p50": percentile(samples, 0.50),
                "p95": percentile(samples, 0.95), "p99": percentile(samples, 0.99),
                "p99_9": percentile(samples, 0.999)},
            "resource_snapshot": resources([*current, "dc-saas-robotsvr"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--location", action="append", default=[], help="Limit measurement to this tenant. Repeat as needed.")
    args = parser.parse_args()
    if not 60 <= args.seconds <= 600:
        parser.error("Use a 60 to 600 second log window")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", location) for location in args.location):
        parser.error("Use valid tenant locations")
    until = datetime.now(timezone.utc)
    print(json.dumps(measure(args.generation, until - timedelta(seconds=args.seconds), until,
                             set(args.location)), indent=2))


if __name__ == "__main__":
    main()
