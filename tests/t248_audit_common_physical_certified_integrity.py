#!/usr/bin/env python3
"""T248 read-only 512-partition Common WAL + Custody + Receipt integrity gate.

Never repairs, signs, writes state, or interprets business order types.
Prints only partition IDs, watermarks, and integrity checks, no private keys.
"""
from hashlib import sha256
from pathlib import Path
import importlib.util
import json

LIB = Path(__file__).with_name("t247_restore_certified_order_trade_wal.py")
spec = importlib.util.spec_from_file_location("t247_validation", LIB)
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


def audit():
    warnings = []
    counts = {}
    for service in ("OrderSvr", "TradeSvr"):
        checked = 0
        for i in range(256):
            part = "P%03d" % i
            bases = (lib.location(service, i, "A"), lib.location(service, i, "B"))
            left, right = (p / "business.wal" for p in bases)
            if not left.exists() or not right.exists():
                warnings.append((service, part, "WAL_MISSING"))
                continue
            a, b = left.read_bytes(), right.read_bytes()
            if a != b:
                warnings.append((service, part, "WAL_A_B_DIFFERENT"))
            for node, root, data in (("A", bases[0], a), ("B", bases[1], b)):
                h = root / "custody/head.bin"
                l = root / "custody-ledger/receipt-quorum.bin"
                if not data and not h.exists() and not l.exists():
                    continue
                checked += 1
                if not h.is_file() or not l.is_file():
                    warnings.append((service, part, node + "_CERTIFICATE_MISSING"))
                    continue
                try:
                    signed = lib.parse_cert(h.read_bytes(), False)
                    ledger = lib.parse_cert(l.read_bytes(), True)
                    seq = lib.frames(data)
                    hash_ = sha256(data).hexdigest()
                    if signed[0] != ledger[0] or signed[1] != ledger[1] or signed[2] != ledger[2]:
                        warnings.append((service, part, node + "_CUSTODY_RECEIPT_MISMATCH",
                                         "head=" + str(signed[:2]), "receipt=" + str(ledger[:2])))
                    if signed[0] != 2 or signed[1] != seq or signed[2] != hash_:
                        warnings.append((service, part, node + "_WAL_SIGNED_HEAD_MISMATCH",
                                         "certified=" + str(signed[:2]), "walSeq=" + str(seq)))
                except Exception as ex:
                    warnings.append((service, part, node + "_READ_ONLY_VERIFY_EXCEPTION",
                                     type(ex).__name__))
        counts[service] = {"partitions": 256, "nonemptyNodeWals": checked}
    return counts, warnings


if __name__ == "__main__":
    counts, problems = audit()
    print(json.dumps({"readOnly": True, "counts": counts, "errorCount": len(problems),
                      "errors": problems[:30]}, indent=2, sort_keys=True))
    if problems:
        raise SystemExit(1)