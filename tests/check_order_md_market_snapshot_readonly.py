#!/usr/bin/env python3
"""Read-only Order snapshot -> MD market coverage preflight.

An Order snapshot digest is not a signed, current durable Order HEAD.
Even a perfect match MUST NOT authorize MD promotion or change ZK.
"""
import argparse
import hashlib
import json
import zlib
from pathlib import Path


def partition(location, market="4", security="BTCUSDT"):
    if not location or any("\x1f" in value for value in (location, market, security)):
        raise ValueError("invalid Order market routing key")
    return "P%03d" % (zlib.crc32((location + "\x1f" + market + "\x1f" + security).encode()) % 256)


def audit(root, tenants):
    findings, blockers, seen = [], [], set()
    if not isinstance(tenants, list) or not tenants:
        raise ValueError("nonempty tenant audit required")
    for tenant in tenants:
        location = tenant.get("location") if isinstance(tenant, dict) else None
        if not isinstance(location, str) or not location.isalnum() or location in seen:
            blockers.append("INVALID_OR_DUPLICATE_TENANT")
            continue
        seen.add(location)
        part = partition(location)
        records = []
        for node in ("OrderSvrA", "OrderSvrB", "OrderSvrC"):
            file = root / node / "snapshot" / part / "snapshot.json"
            try:
                # Reject symlinks so this auditor never follows external content.
                if file.is_symlink() or not file.is_file() or file.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError("unsafe or missing full snapshot")
                raw = file.read_bytes()
                snapshot = json.loads(raw)
                books = snapshot.get("books")
                if not isinstance(books, list) or not books:
                    raise ValueError("empty Order market inventory")
                # Full-partition inventory: every book must route back to the
                # requested partition; matching only the selected market can
                # hide missing or misplaced books during a promotion.
                book_keys = set()
                for book in books:
                    identity = (book.get("location"), str(book.get("marketIndicator")),
                                book.get("securityId"))
                    if any(not isinstance(part, str) or not part for part in identity):
                        raise ValueError("invalid full market identity")
                    if identity in book_keys or partition(*identity) != part:
                        raise ValueError("duplicate or misplaced full-market entry")
                    if int(book.get("lastUpdateId", -1)) < 0:
                        raise ValueError("invalid source depth prefix")
                    book_keys.add(identity)
                matches = [b for b in books if (b.get("location"), str(b.get("marketIndicator")),
                             b.get("securityId")) == (location, "4", "BTCUSDT")]
                if len(matches) != 1:
                    raise ValueError("missing or duplicate routed market")
                marker = int(snapshot.get("commitMarkerSeq", 0))
                seq = int(snapshot.get("snapshotSeq", 0))
                committed = int(snapshot.get("committedStateSeq", -1))
                epoch = int(snapshot.get("epoch", 0))
                committed_epoch = int(snapshot.get("committedStateEpoch", 0))
                if (snapshot.get("partitionId") != part or epoch < 1 or seq < 1
                        or marker != seq or committed < 0 or committed >= marker
                        or committed_epoch < 1 or committed_epoch > epoch):
                    raise ValueError("invalid Order commit marker")
                if int(matches[0].get("lastUpdateId", -1)) < 0:
                    raise ValueError("invalid source market version")
                records.append(dict(node=node, epoch=epoch, seq=seq,
                    marketUpdateId=int(matches[0]["lastUpdateId"]),
                    sha256=hashlib.sha256(raw).hexdigest()))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                blockers.append("%s:%s:%s" % (part, node, type(exc).__name__))
        if len(records) == 3 and len({(x["epoch"], x["seq"], x["sha256"]) for x in records}) != 1:
            blockers.append("%s:ORDER_REPLICA_SNAPSHOT_MISMATCH" % part)
        findings.append(dict(partition=part, location=location, matchedNodes=len(records), replicas=records))
    return {
        "checkedTenants": len(seen),
        "verifiedTriplicateSnapshots": sum(len(x["replicas"]) == 3 and
             len({(r["epoch"], r["seq"], r["sha256"]) for r in x["replicas"]}) == 1 for x in findings),
        "snapshotIssues": blockers,
        "snapshots": findings,
        # Explicitly NOT a durable Order proof or shared publication fence.
        "orderDurableSignedHeadAndAckProof": "NOT_CHECKED",
        "mdOldPublisherFenceProof": "NOT_CHECKED",
        "mdFullMarketImageAndDeltaProof": "NOT_CHECKED",
        "promotionAuthorized": False,
        "decision": "BLOCKED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--tenant-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tenant_info = json.loads(args.tenant_audit.read_text())
    result = audit(args.data_root, tenant_info["tenants"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k,v in result.items() if k not in ("snapshots",)}, sort_keys=True))
    return 0 if not result["snapshotIssues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())