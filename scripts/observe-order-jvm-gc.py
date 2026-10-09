#!/usr/bin/env python3
"""Sample HotSpot Java 8 GC/safepoint counters inside running Order containers.

No JVM attach, signal, code injection, service restart or data mutation.
Read the running JVM's /tmp/hsperfdata_* file through docker exec,
without assuming Java has a specific PID, then emit interval deltas.
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
OLD_USED = "sun.gc.generation.1.space.0.used"
OLD_CAPACITY = "sun.gc.generation.1.space.0.capacity"
OLD_MAX_CAPACITY = "sun.gc.generation.1.space.0.maxCapacity"



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
    # The JVM PID is not stable across replica images: Order A currently has
    # pid=6 while B/C have pid=7. Select the one live Java PerfData file,
    # never assume /tmp/hsperfdata_root/7 or touch the Java process.
    select_live_perfdata = (
        'chosen=""; '
        'for f in /tmp/hsperfdata_*/*; do '
        '[ -f "$f" ] || continue; '
        'pid="${f##*/}"; '
        'case "$pid" in *[!0-9]*|"") continue;; esac; '
        '[ -r "/proc/$pid/comm" ] || continue; '
        '[ "$(cat "/proc/$pid/comm" 2>/dev/null)" = "java" ] || continue; '
        '[ -z "$chosen" ] || exit 4; '
        'chosen="$f"; '
        'done; '
        '[ -n "$chosen" ] || exit 3; '
        'base64 "$chosen"'
    )
    result = subprocess.run(["docker", "exec", node, "sh", "-c",
                             select_live_perfdata],
                            capture_output=True, text=True, timeout=18)
    if result.returncode != 0:
        raise RuntimeError("cannot select live JVM PerfData from %s (status=%d)" %
                           (node, result.returncode))
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


def old_generation_capacity(values):
    """Report live old-generation occupancy, rather than only GC CPU time."""
    if OLD_USED not in values or OLD_CAPACITY not in values:
        return None
    used, capacity = values[OLD_USED], values[OLD_CAPACITY]
    if used < 0 or capacity <= 0 or used > capacity:
        raise ValueError("inconsistent old-generation occupancy")
    return (used / (1024.0 ** 2), capacity / (1024.0 ** 2),
            100.0 * used / capacity)


def old_generation_max_capacity(values):
    """Compare usage against JVM maximum rather than recently committed old space."""
    committed = old_generation_capacity(values)
    if committed is None or OLD_MAX_CAPACITY not in values:
        return None
    max_bytes = values[OLD_MAX_CAPACITY]
    if max_bytes <= 0 or max_bytes < values[OLD_CAPACITY]:
        raise ValueError("inconsistent old-generation max capacity")
    return (committed[0], max_bytes / (1024.0 ** 2),
            100.0 * values[OLD_USED] / max_bytes)


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
                    old = old_generation_capacity(current[name])
                    old_max = old_generation_max_capacity(current[name])
                    old_text = (
                        (" old_used_mib=%.1f old_committed_mib=%.1f "
                         "old_committed_pct=%.2f") % old
                        + (" old_max_mib=%.1f old_max_pct=%.2f"
                           % (old_max[1], old_max[2]) if old_max is not None
                           else " old_max=unknown")
                    ) if old is not None else " old_occupancy=unknown"
                    print(("%s %s young=%d young_ms=%.1f full=%d full_ms=%.1f "
                           "safepoint_ms=%.1f sync_ms=%.1f") %
                          (now, name, delta["young_count"], delta["young_ticks"],
                           delta["full_count"], delta["full_ticks"],
                           delta["safepoint_ticks"],
                           delta["safepoint_sync_ticks"]) + old_text, flush=True)
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
