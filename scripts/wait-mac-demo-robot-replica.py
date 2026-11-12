#!/usr/bin/env python3
"""Check physical replica snapshot progress on a real Robot's fresh service shard."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import zlib


READ_PIN = r'''
set -eu
d="$1"
p="$d/opaque-v2-replica.pin"
test -f "$p" || exit 0
test ! -L "$p"
printf 'PIN '; cat "$p"
for f in "$d"/unverified-recovery-*/VERIFIED_STAGING_NOT_READY; do
    test -f "$f" || continue
    test ! -L "$(dirname "$f")"
    test ! -L "$f"
    printf '%s ' "$(basename "$(dirname "$f")")"
    sed -n 's/^snapshotSeq=\([0-9][0-9]*\)$/\1/p' "$f"
done
'''


def marker_progress(witness, slot, partition, service="OrderSvr"):
    path = (f"/srv/dc/data/t554-voter-{slot}/replica-snapshots/{service}/"
            f"{service}{slot.upper()}/{partition}/epoch-2")
    lines = subprocess.check_output(["docker", "exec", witness, "sh", "-c", READ_PIN, "--", path],
                                    text=True, timeout=25).splitlines()
    if not lines:
        return None
    if not re.fullmatch(r"PIN unverified-recovery-\d+", lines[0]):
        raise RuntimeError("Invalid physical snapshot pin")
    pin = lines[0].split()[1]
    marks = {}
    for line in lines[1:]:
        if not re.fullmatch(r"unverified-recovery-\d+ \d+", line):
            raise RuntimeError("Invalid verified snapshot marker")
        locator, sequence = line.split()
        marks[locator] = int(sequence)
    if pin not in marks:
        # A new pin may move while the read-only directory scan is running.
        return None
    latest = marks[pin]
    prior = [(sequence, locator) for locator, sequence in marks.items() if latest - sequence >= 256]
    if latest < 512 or not prior:
        return None
    first, previous = max(prior)
    return {"initial_snapshot": first, "refreshed_snapshot": latest,
            "initial_locator": previous, "locator": pin, "same_exact_disk_verified_markers": True}


def wait(root, service="order"):
    generation = root.name
    if not re.fullmatch(r"mac-demo-\d{8}-\d{6}", generation) or any(root.glob("ha-*/evidence.json")):
        raise RuntimeError("Expected a fresh Mac Demo generation")
    active = subprocess.check_output(["docker", "inspect", "--format",
        '{{index .Config.Labels "com.docker.compose.project"}}', "dc-saas-gateway"], text=True, timeout=15).strip()
    if active != generation:
        raise RuntimeError("Gateway is not on the requested generation")
    reports = sorted(root.glob("verification.*/robot-tape-e2e.json"), key=lambda p: p.stat().st_mtime)
    baseline = json.loads(reports[-1].read_text()) if reports else {}
    if baseline.get("status") != "PASS_LIVE_BUSINESS_NOT_HA":
        raise RuntimeError("Expected a passing baseline from real Robot and Tape activity")
    hot = {}
    for location, count in baseline["tape_filled_by_location"].items():
        if count > 0 and re.fullmatch(r"[A-Z0-9]{6}", location):
            route_key = f"{location}\x1f4\x1fBTCUSDT" if service == "order" else location
            shard = zlib.crc32(route_key.encode()) % 256
            hot[f"P{shard:03d}"] = (location, "b" if shard < 128 else "a")
    if not hot:
        raise RuntimeError("No real Robot Tape tenant in the baseline")
    print(f"Waiting for verified physical replica snapshots under live Robot flow {sorted(hot)}", flush=True)
    voter_service = "OrderSvr" if service == "order" else "TradeSvr"
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        for shard, (location, replica) in hot.items():
            result = marker_progress(generation + f"-{service}-witness", replica, shard, voter_service)
            if result is None:
                continue
            result.update(service=voter_service, partition=shard, robot_location=location, voter_slot=replica,
                          primary_slot="A" if replica == "b" else "B")
            filename = ("robot-replica-snapshot-advance.json" if service == "order"
                        else "robot-trade-replica-snapshot-advance.json")
            output = root / filename
            pending = output.with_suffix(".tmp")
            pending.write_text(json.dumps(result, indent=2) + "\n")
            pending.replace(output)
            print(json.dumps(result), flush=True)
            return
        time.sleep(10)
    raise RuntimeError("No new physical replica snapshot under real Robot flow in the bounded wait")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("--service", choices=("order", "trade"), default="order")
    args = parser.parse_args()
    wait(args.generation.resolve(strict=True), args.service)
