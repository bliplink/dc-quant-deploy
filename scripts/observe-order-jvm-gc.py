#!/usr/bin/env python3
"""Sample HotSpot Java 8 GC/safepoint counters inside running Order containers.

No JVM attach, signal, code injection, service restart or data mutation.
Read /tmp/hsperfdata_root/7 through docker exec, then emit interval deltas.
Cumulative GC time does not establish the maximum stop-the-world pause.
Correlate with ZooKeeper Expired timestamps and VM CPU PSI before attribution.
"""
import argparse
import base64
import datetime
import struct
import subprocess
import sys
import time

NODES = ("dc-saas-ordersvr", "dc-saas-ordersvr-b", "dc-saas-ordersvr-c")
COUNTERS = {
    "young_count": "sun.gc.collector.0.invocations",
    "young_ticks": "sun.gc.collector.0.time",
    "full_count": "sun.gc.collector.1.invocations",
    "full_ticks": "sun.gc.collector.1.time",
    "safepoint_ticks": "sun.rt.safepointTime",
    "safepoint_sync_ticks": "sun.rt.safepointSyncTime",
}
FREQ = "sun.os.hrt.frequency"


def parse_perfdata(raw):
    """Parse a bounded HotSpot PerfData V2 buffer; no external dependencies."""
    if len(raw) < 32 or raw[:4] != bytes.fromhex("cafec0c0"):
        raise ValueError("invalid HotSpot PerfData header")
    # 1 = little-endian (byte_order field), 0 = big-endian.
    if raw[4] not in (0, 1) or raw[5] != 2:
        raise ValueError("unsupported PerfData byte order/version")
    endian = "<" if raw[4] == 1 else ">"
    used = struct.unpack_from(endian + "I", raw, 8)[0]
    offset, count = struct.unpack_from(endian + "II", raw, 24)
    if not (32 <= used <= len(raw) and 32 <= offset < used and 0 < count <= 4096):
        raise ValueError("malformed PerfData bounds")
    values = {}
    for _ in range(count):
        if offset + 20 > used:
            raise ValueError("truncated PerfData record")
        length, name_offset, vector_length = struct.unpack_from(endian + "III", raw, offset)
        data_type = chr(raw[offset + 12])
        data_offset = struct.unpack_from(endian + "I", raw, offset + 16)[0]
        if length < 20 or offset + length > used:
            raise ValueError("bad PerfData record length")
        name_start = offset + name_offset
        name_end = raw.find(b"\x00", name_start, offset + length)
        if not (offset + 20 <= name_start < name_end):
            raise ValueError("bad PerfData record name")
        name = raw[name_start:name_end].decode("utf-8")
        if data_type == "J" and vector_length == 0 and 20 <= data_offset <= length - 8:
            values[name] = struct.unpack_from(endian + "q", raw, offset + data_offset)[0]
        offset += length
    if not all(x in values for x in tuple(COUNTERS.values()) + (FREQ,)):
        raise ValueError("required JVM GC counters not available")
    if values[FREQ] <= 0:
        raise ValueError("invalid high-resolution clock frequency")
    return values


def read_node(node):
    result = subprocess.run(["docker", "exec", node, "base64",
                             "/tmp/hsperfdata_root/7"],
                            capture_output=True, text=True, timeout=18)
    if result.returncode != 0:
        raise RuntimeError("cannot read HotSpot PerfData from %s: %s" %
                           (node, result.stderr[:160]))
    return parse_perfdata(base64.b64decode(result.stdout, validate=False))


def interval(prev, current):
    """GC counts and accumulated milliseconds for a single sampling interval."""
    hz = current[FREQ]
    if prev[FREQ] != hz:
        raise ValueError("JVM clock changed (container restarted?)")
    result = {}
    for label, counter in COUNTERS.items():
        delta = current[counter] - prev[counter]
        if delta < 0:
            raise ValueError("JVM counter decreased (restart or inconsistent read)")
        result[label] = delta / hz * 1000.0 if label.endswith("ticks") else delta
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()
    if args.samples < 2 or args.samples > 180 or not (1 <= args.interval <= 60):
        parser.error("samples must be 2..180 and interval 1..60 seconds")
    previous = None
    for iteration in range(args.samples):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            current = {name: read_node(name) for name in NODES}
            if previous is not None:
                for name in NODES:
                    delta = interval(previous[name], current[name])
                    print("%s %s young=%d young_ms=%.1f full=%d full_ms=%.1f "
                          "safepoint_ms=%.1f sync_ms=%.1f" %
                          (now, name, delta["young_count"], delta["young_ticks"],
                           delta["full_count"], delta["full_ticks"],
                           delta["safepoint_ticks"],
                           delta["safepoint_sync_ticks"]), flush=True)
            else:
                print("%s JVM counters baseline read from all three Order nodes" % now, flush=True)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            print("NO_DATA: " + str(error), file=sys.stderr)
            return 2
        previous = current
        if iteration + 1 < args.samples:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
