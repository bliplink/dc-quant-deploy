"""HotSpot Java 8 PerfData parser and GC delta tests; no Docker required."""
import importlib.util
from pathlib import Path
import struct
import unittest

SOURCE = (Path(__file__).resolve().parent.parent /
          "scripts" / "observe-order-jvm-gc.py")
spec = importlib.util.spec_from_file_location("order_gc_perfdata", str(SOURCE))
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)


def perfdata(extra=None):
    values = {
        "sun.os.hrt.frequency": 1_000_000_000,
        "sun.gc.collector.0.invocations": 2,
        "sun.gc.collector.0.time": 2_000_000_000,
        "sun.gc.collector.1.invocations": 1,
        "sun.gc.collector.1.time": 3_000_000_000,
        "sun.rt.safepointTime": 5_000_000_000,
        "sun.rt.safepointSyncTime": 200_000_000,
    }
    if extra:
        values.update(extra)
    entries = []
    for name, value in values.items():
        name_bytes = name.encode("utf-8") + b"\x00"
        data_offset = 20 + len(name_bytes)
        length = data_offset + 8
        blob = bytearray(length)
        struct.pack_into("<III", blob, 0, length, 20, 0)
        blob[12] = ord("J")
        struct.pack_into("<I", blob, 16, data_offset)
        blob[20:data_offset] = name_bytes
        struct.pack_into("<q", blob, data_offset, value)
        entries.append(blob)
    used = 32 + sum(len(x) for x in entries)
    raw = bytearray(used)
    raw[:4] = bytes.fromhex("cafec0c0")
    raw[4] = 1
    raw[5] = 2
    struct.pack_into("<I", raw, 8, used)
    struct.pack_into("<II", raw, 24, 32, len(entries))
    cursor = 32
    for entry in entries:
        raw[cursor:cursor + len(entry)] = entry
        cursor += len(entry)
    return bytes(raw)


class OrderGcPerfDataTest(unittest.TestCase):
    def test_parses_valid_little_endian_hotspot_data(self):
        counters = gc.parse_perfdata(perfdata())
        self.assertEqual(1_000_000_000, counters[gc.FREQ])
        self.assertEqual(2, counters["sun.gc.collector.0.invocations"])
        self.assertEqual(5_000_000_000, counters["sun.rt.safepointTime"])

    def test_rejects_corrupt_and_truncated_header(self):
        with self.assertRaises(ValueError):
            gc.parse_perfdata(b"")
        bad = b"\x00" * 32
        with self.assertRaises(ValueError):
            gc.parse_perfdata(bad)

    def test_rejects_missing_gc_counters(self):
        x = bytearray(perfdata())
        at = x.find(b"sun.gc.collector.0.time")
        x[at:at + 2] = b"XX"
        with self.assertRaises(ValueError):
            gc.parse_perfdata(bytes(x))

    def test_intervals_report_only_delta_and_convert_ticks_to_ms(self):
        old = gc.parse_perfdata(perfdata())
        new = gc.parse_perfdata(perfdata({
            "sun.gc.collector.0.invocations": 5,
            "sun.gc.collector.0.time": 2_450_000_000,
            "sun.gc.collector.1.invocations": 1,
            "sun.gc.collector.1.time": 3_000_000_000,
            "sun.rt.safepointTime": 5_750_000_000,
            "sun.rt.safepointSyncTime": 260_000_000,
        }))
        d = gc.interval(old, new)
        self.assertEqual(3, d["young_count"])
        self.assertAlmostEqual(450., d["young_ticks"])
        self.assertEqual(0, d["full_count"])
        self.assertAlmostEqual(750., d["safepoint_ticks"])
        self.assertAlmostEqual(60., d["safepoint_sync_ticks"])

    def test_decreased_counter_fails_closed(self):
        current = gc.parse_perfdata(perfdata())
        previous = gc.parse_perfdata(perfdata({
            "sun.gc.collector.0.invocations": 100
        }))
        with self.assertRaises(ValueError):
            gc.interval(previous, current)

    def test_changed_clock_fails_closed(self):
        previous = gc.parse_perfdata(perfdata())
        current = gc.parse_perfdata(perfdata({"sun.os.hrt.frequency": 10_000_000}))
        with self.assertRaises(ValueError):
            gc.interval(previous, current)


if __name__ == "__main__":
    unittest.main()
