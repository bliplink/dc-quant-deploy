#!/usr/bin/env python3
"""Read-only pre-restart A/B Common WAL census. Never repairs, truncates or ACKs."""
from pathlib import Path
import os
import struct
import sys
import zlib

ROOT = Path(os.environ.get(
    "T328_SIGNED_ORDER_WAL_ROOT",
    str(Path.home() / ".opentradingcore/dc-saas-runtime-clean-20261016/"
        "data/t325-trading-e2/OrderSvr")))

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
            unmatched.append((part, ac, bc, ac - bc))
        else:
            print("T328_WAL_DIVERGED_NOT_PREFIX partition="+part)
            return 3
    print("T328_ORIGINAL_WAL_CENSUS_PARTITION_EQUAL=%d/256" % identical)
    for p, ac, bc, excess in unmatched:
        print("T328_UNCERTIFIED_A_TAIL partition=%s aRecords=%d bRecords=%d excessRecords=%d" % (p, ac, bc, excess))
    if unmatched:
        print("T328_ORDER_A_RESTART_BLOCKED unsignedTailPartitions=%d "
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
