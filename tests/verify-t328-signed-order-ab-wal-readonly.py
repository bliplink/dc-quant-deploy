#!/usr/bin/env python3
"""Read-only pre-restart A/B Common WAL census. Never repairs, truncates or ACKs."""
from pathlib import Path
import os
import struct
import sys
import zlib

# Avoid silently inspecting a stale generation (the former T325 default).
# Explicitly select the exact root for the run being audited.
RAW_ROOT = os.environ.get("T328_SIGNED_ORDER_WAL_ROOT", "").strip()
ROOT = Path(RAW_ROOT).expanduser() if RAW_ROOT else None

def inspect(wal):
    data = wal.read_bytes()
    pos = 0
    seq = 0
    while pos < len(data):
        if pos + 28 > len(data):
            raise ValueError("torn WAL header")
        magic, epoch, n, size, crc = struct.unpack_from(">IqqII", data, pos)
        if magic != 0x43425731 or epoch != 2 or n != seq + 1 or size <= 0 or size > 16 * 1024 * 1024 or pos + 28 + size > len(data):
            raise ValueError("noncontiguous or invalid Common E2 frame")
        payload = data[pos + 28: pos + 28 + size]
        if zlib.crc32(struct.pack(">qq", epoch, n) + payload) & 0xffffffff != crc:
            raise ValueError("invalid WAL checksum")
        seq = n
        pos += 28 + size
    return data, seq

def main():
    if ROOT is None or not ROOT.is_absolute() or not ROOT.is_dir() or ROOT.is_symlink():
        print("T328_WAL_ROOT_REQUIRED: set T328_SIGNED_ORDER_WAL_ROOT to an existing absolute non-symlink OrderSvr generation root", file=sys.stderr)
        return 4
    print("T328_SIGNED_ORDER_WAL_ROOT=" + str(ROOT))
    identical = 0
    unmatched = []
    for i in range(256):
        part = "P%03d" % i
        records = {}
        for n in ("A", "B"):
            wal = ROOT / ("OrderSvr"+n) / "OrderSvr" / ("OrderSvr"+n) / part / "epoch-2" / "business.wal"
            if not wal.is_file() or wal.is_symlink():
                raise ValueError("missing/link WAL " + str(wal))
            records[n] = inspect(wal)
        a, ac = records["A"]
        b, bc = records["B"]
        if a == b:
            identical += 1
        elif a.startswith(b):
            unmatched.append((part, 'A', ac, bc, ac - bc))
        elif b.startswith(a):
            # P193's certified primary is B, so a B-leading tail is NOT
            # a fork. It is still unsafe for live writes until independently
            # certified and reconciled. Never silently accept it.
            unmatched.append((part, 'B', ac, bc, bc - ac))
        else:
            print("T328_WAL_DIVERGED_NOT_PREFIX partition="+part)
            return 3
    print("T328_ORIGINAL_WAL_CENSUS_PARTITION_EQUAL=%d/256" % identical)
    for p, leader, ac, bc, excess in unmatched:
        print("T328_UNRECONCILED_%s_TAIL partition=%s aRecords=%d bRecords=%d excessRecords=%d" %
              (leader, p, ac, bc, excess))
    if unmatched:
        print("T328_ORDER_AB_RESTART_BLOCKED unmatchedTailPartitions=%d "
              "noTruncation=true noBusinessApply=true" % len(unmatched))
        return 2
    print("T328_ORDER_WAL_BYTE_IDENTICAL_PASS partitions=256")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print("T328_WAL_EVIDENCE_INVALID: %s" % error, file=sys.stderr)
        sys.exit(4)
