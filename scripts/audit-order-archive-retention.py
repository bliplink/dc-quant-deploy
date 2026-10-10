#!/usr/bin/env python3
"""Read-only OrderSvr archive footprint inventory. Never deletes or grants GC.

The archived CQ directory name is only a *hint* at pre-rebase journal state,
not proof of commit index, Projection persistence, replica catch-up or rollback
safety. In the absence of signed authoritative proofs everything is pinned.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ARCHIVE_NAME = re.compile(r"^(P\d{3})-epoch(\d+)-seq(\d+)-(\d+)$")


def inventory(journal_path):
    root = Path(journal_path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("journal directory must be an existing nonsymlink directory")
    archive = root / ".archive"
    if archive.is_symlink() or not archive.is_dir():
        raise ValueError("archive directory must be an existing nonsymlink directory")
    details = []
    for candidate in sorted(archive.iterdir()):
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("archive contains an unsafe symlink or non-directory entry")
        match = ARCHIVE_NAME.fullmatch(candidate.name)
        if not match:
            raise ValueError("unexpected archive directory naming; retention audit aborted")
        logical = physical = files = 0
        for base, dirs, names in os.walk(candidate, followlinks=False):
            for name in dirs + names:
                p = Path(base) / name
                if p.is_symlink():
                    raise ValueError("archive contains a symlink; retention audit aborted")
            for name in names:
                file = Path(base) / name
                if not file.is_file():
                    raise ValueError("archive contains a non-regular file")
                stat = file.stat()
                logical += stat.st_size
                physical += stat.st_blocks * 512 if hasattr(stat, "st_blocks") else stat.st_size
                files += 1
        details.append({
            "archive": candidate.name, "partition": match.group(1),
            "epochNameHint": int(match.group(2)),
            "lastSequenceNameHint": int(match.group(3)),
            "fileCount": files, "logicalBytes": logical,
            "allocatedBytes": physical,
            "retentionDecision": "HOLD", "deletionAuthorized": False,
            "blockedBy": ["NO_AUTHORITATIVE_WATERMARK_ATTESTATION",
                          "REPLICA_RECOVERY_NOT_ATTESTED",
                          "PROJECTION_CONSUMER_NOT_ATTESTED",
                          "OFFSITE_BACKUP_RESTORE_NOT_ATTESTED"],
        })
    return {
        "node": root.parent.name, "journalDir": str(root),
        "archives": len(details),
        "logicalBytes": sum(x["logicalBytes"] for x in details),
        "allocatedBytes": sum(x["allocatedBytes"] for x in details),
        "archiveDetails": details,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", action="append", required=True,
                        help="OrderSvr node journal directory; repeat per node")
    parser.add_argument("--output", help="write full JSON inventory here (never under journal root)")
    args = parser.parse_args(argv)
    results = [inventory(path) for path in args.journal]
    for root in args.journal:
        if args.output:
            output = Path(args.output).resolve()
            journal = Path(root).resolve()
            if output == journal or journal in output.parents:
                raise ValueError("output must not be written inside an OrderSvr journal")
    data = {
        "schema": "otc-order-archive-audit-v1",
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_NO_DELETE", "deletionAuthorized": False,
        "totalArchives": sum(v["archives"] for v in results),
        "totalAllocatedBytes": sum(v["allocatedBytes"] for v in results),
        "totalLogicalBytes": sum(v["logicalBytes"] for v in results),
        "blockedArchives": sum(v["archives"] for v in results),
        "nodes": results,
        "warning": "Folder names and file ages are not safe commit or recovery watermarks. Never delete from this report.",
    }
    if args.output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    summary = {k: v for k, v in data.items() if k != "nodes"}
    summary["nodes"] = [{k: v for k, v in node.items() if k != "archiveDetails"} for node in results]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print("archive audit failed closed: " + str(exc), file=sys.stderr)
        sys.exit(2)
