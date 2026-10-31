#!/usr/bin/env python3
"""Read-only physical WAL parity audit for two Common Order/Trade nodes.

Does not issue or verify RSA certificates, activate READY, truncate WAL, or
write to ZooKeeper. Certificate metadata is informational; Common owns the
actual quorum signature verification.
"""
import argparse
import hashlib
import json
import pathlib
import struct
import zlib

FRAME_MAGIC = 0x43425731
HEAD_MAGIC = b"OTCC"
FRAME_HEADER = 28
MAX_PAYLOAD = 16 * 1024 * 1024


def scan_wal(path, epoch):
    if not path.is_file() or path.is_symlink():
        return None
    data = path.read_bytes()
    offset = 0
    sequence = 0
    while offset < len(data):
        if len(data) - offset < FRAME_HEADER:
            raise ValueError(f"{path}: incomplete frame header at {offset}")
        magic, frame_epoch, frame_seq, length, checksum = struct.unpack_from(">IQQII", data, offset)
        if magic != FRAME_MAGIC or frame_epoch != epoch or frame_seq != sequence + 1:
            raise ValueError(f"{path}: invalid frame at offset={offset} seq={frame_seq}")
        if length > MAX_PAYLOAD or offset + FRAME_HEADER + length > len(data):
            raise ValueError(f"{path}: truncated/unbounded frame seq={frame_seq}")
        body = data[offset + FRAME_HEADER:offset + FRAME_HEADER + length]
        actual = zlib.crc32(struct.pack(">QQ", frame_epoch, frame_seq) + body) & 0xFFFFFFFF
        if checksum != actual:
            raise ValueError(f"{path}: incorrect CRC seq={frame_seq}")
        sequence = frame_seq
        offset += FRAME_HEADER + length
    return {"frames": sequence, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def inspect_head(path):
    if not path.is_file() or path.is_symlink():
        return None
    data = path.read_bytes()
    if len(data) < 82 or data[:4] != HEAD_MAGIC or struct.unpack_from(">I", data, 4)[0] != 1:
        raise ValueError(f"{path}: unknown custody HEAD header")
    digest_length = struct.unpack_from(">H", data, 8)[0]
    if digest_length != 64 or len(data) < 10 + digest_length + 8:
        raise ValueError(f"{path}: unknown custody HEAD metadata")
    claimed_seq = struct.unpack_from(">Q", data, 10 + digest_length)[0]
    return {"declared_sequence": claimed_seq, "bytes": len(data),
            "file_sha256": hashlib.sha256(data).hexdigest()}


def audit(a, b, epoch, partitions):
    mismatches = []
    active = 0
    both = 0
    maxseq = 0
    for i in range(partitions):
        pid = f"P{i:03d}"
        pa, pb = (root / pid / f"epoch-{epoch}" for root in (a, b))
        wa, wb = scan_wal(pa / "business.wal", epoch), scan_wal(pb / "business.wal", epoch)
        ha, hb = inspect_head(pa / "custody" / "head.bin"), inspect_head(pb / "custody" / "head.bin")
        if wa or wb:
            active += 1
        if wa and wb:
            both += 1
            maxseq = max(maxseq, wa["frames"], wb["frames"])
        error = []
        if wa is None or wb is None:
            error.append("missing_physical_wal")
        elif wa["sha256"] != wb["sha256"]:
            error.append("wal_divergence")
        for node, wal, head in (("A", wa, ha), ("B", wb, hb)):
            if head and (not wal or head["declared_sequence"] > wal["frames"]):
                error.append(f"{node}_head_ahead_of_wal")
        if bool(ha) != bool(hb) or (ha and hb and ha["file_sha256"] != hb["file_sha256"]):
            error.append("custody_head_differs")
        if error:
            mismatches.append({"partition": pid, "reasons": error,
                               "a_frames": wa["frames"] if wa else None,
                               "b_frames": wb["frames"] if wb else None,
                               "a_head": ha["declared_sequence"] if ha else None,
                               "b_head": hb["declared_sequence"] if hb else None})
    return {"epoch": epoch, "checked": partitions, "active": active,
            "both_wal_present": both, "highest_frame": maxseq,
            "mismatch_count": len(mismatches), "mismatches": mismatches[:25],
            "warning": "physical checksum audit only; Common must verify cryptographic signer/quorum"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--a", type=pathlib.Path, required=True, help="A node's local partition parent directory")
    p.add_argument("--b", type=pathlib.Path, required=True, help="B node's local partition parent directory")
    p.add_argument("--epoch", type=int, default=2)
    p.add_argument("--partitions", type=int, default=256)
    args = p.parse_args()
    if not (0 < args.epoch < 10000 and 1 <= args.partitions <= 256):
        p.error("invalid epoch or partition count")
    for root in (args.a, args.b):
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            p.error("existing absolute non-symlink node partition roots required")
    result = audit(args.a, args.b, args.epoch, args.partitions)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["mismatch_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
