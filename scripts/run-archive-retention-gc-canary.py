#!/usr/bin/env python3
"""Execute REAL archive GC only on an internally created disposable canary.

This tool DOES NOT accept the location of an existing archive to delete.
It deliberately cannot target live Order/Trade WAL. Production needs
independent signed replica/projection/backup read witnesses first.
"""
from __future__ import annotations
import argparse
import dataclasses
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

ARCHIVE = re.compile(r"^(P[0-9]{3})-epoch([1-9][0-9]*)-seq([0-9]+)-([0-9]+)$")
MIN_AGE_SECONDS = 7 * 24 * 3600


@dataclasses.dataclass(frozen=True)
class RetentionWitness:
    expected_partition: str
    expected_last_seq: int
    snapshot_durable_seq: int
    replica_durable: tuple[int, ...]
    projection_durable_seq: int
    backup_verified: bool
    readers_active: int
    source_recoverable: bool
    now: float


def require_gc_safe(archive: Path, proof: RetentionWitness, minimum_age: int = MIN_AGE_SECONDS):
    if not isinstance(archive, Path) or archive.is_symlink() or not archive.is_dir():
        raise ValueError("archive is absent or linked")
    match = ARCHIVE.fullmatch(archive.name)
    if not match:
        raise ValueError("unrecognized CQ archive name")
    part, epoch, seq, _timestamp = match.groups()
    last = int(seq)
    if part != proof.expected_partition or last != proof.expected_last_seq:
        raise ValueError("archive identity and proof disagree")
    if minimum_age < MIN_AGE_SECONDS:
        raise ValueError("retention is below mandatory minimum")
    if not proof.replica_durable or len(proof.replica_durable) < 2:
        raise ValueError("all required replicas must provide durable proofs")
    if (min(proof.replica_durable) < last or proof.projection_durable_seq < last
            or proof.snapshot_durable_seq < last):
        raise ValueError("current replicas, projection or snapshot still need archive")
    if not proof.backup_verified or not proof.source_recoverable or proof.readers_active:
        raise ValueError("backup restore, source recovery, or open reader gate failed")
    for item in archive.iterdir():
        if item.is_symlink() or not item.is_file() or item.name != "data-0000.cq4":
            raise ValueError("canary archive has an unrecognized or linked member")
        if proof.now - item.stat().st_mtime < minimum_age:
            raise ValueError("archive retained until safe age")
    return True


def execute_canary(evidence_file: Path):
    """Generate all fixtures here; no caller-supplied WAL paths are accepted."""
    if evidence_file.exists() or evidence_file.is_symlink():
        raise ValueError("do not overwrite an existing report")
    with tempfile.TemporaryDirectory(prefix="otc-owned-archive-gc-canary-") as ephemeral:
        owned = Path(ephemeral).resolve()
        journal = owned / "journal"
        archive_root = journal / ".archive"
        archive_root.mkdir(parents=True)
        backup_root = owned / "backup"
        backup_root.mkdir()
        body = b"CHRONICLE-CANARY-ONLY\nstate_seq=119\ncommit_seq=120\n"
        source_digest = hashlib.sha256(body).hexdigest()
        expired = archive_root / "P200-epoch3-seq120-123456"
        expired.mkdir()
        active = expired / "data-0000.cq4"
        active.write_bytes(body)
        os.utime(active, (time.time()-MIN_AGE_SECONDS-3600,
                          time.time()-MIN_AGE_SECONDS-3600))
        backup = backup_root / "data-0000.cq4"
        backup.write_bytes(body)
        backup_sha = hashlib.sha256(backup.read_bytes()).hexdigest()
        assert backup_sha == source_digest

        future = archive_root / "P201-epoch3-seq130-123457"
        future.mkdir()
        pending = future / "data-0000.cq4"
        pending.write_bytes(b"CHRONICLE-CANARY-ONLY\nstate_seq=129\ncommit_seq=130\n")
        os.utime(pending, (time.time()-MIN_AGE_SECONDS-3600,
                           time.time()-MIN_AGE_SECONDS-3600))

        proven = RetentionWitness("P200",120,120,(120,121),120,
                                  backup_verified=True,readers_active=0,
                                  source_recoverable=True,now=time.time())
        require_gc_safe(expired, proven)

        # Prove fail-closed negative gates BEFORE any physical deletion.
        rejected = []
        wrong = [
            ("replica_lag",dataclasses.replace(proven,replica_durable=(120,119))),
            ("projection_lag",dataclasses.replace(proven,projection_durable_seq=119)),
            ("snapshot_lag",dataclasses.replace(proven,snapshot_durable_seq=119)),
            ("reader_open",dataclasses.replace(proven,readers_active=1)),
            ("backup_unverified",dataclasses.replace(proven,backup_verified=False)),
            ("source_unrecoverable",dataclasses.replace(proven,source_recoverable=False)),
            ("replica_missing",dataclasses.replace(proven,replica_durable=(120,))),
        ]
        for reason,proof in wrong:
            try:
                require_gc_safe(expired,proof)
            except ValueError:
                rejected.append(reason)
            else:
                raise AssertionError("unsafe candidate passed GC: "+reason)
        try:
            require_gc_safe(future,dataclasses.replace(proven,expected_partition="P201",
                                                       expected_last_seq=130))
        except ValueError:
            rejected.append("ahead_of_watermarks")
        else:
            raise AssertionError("future archive must be retained")

        # A production collector must supply a remotely restored snapshot
        # and trusted watermarks; these are generated fixtures for the canary.
        # Actual deletion is restricted to this tool's generated path.
        if expired.parent != owned / "journal/.archive":
            raise AssertionError("GC escaped the disposable canary")
        active.unlink()
        expired.rmdir()
        if expired.exists() or not pending.exists():
            raise AssertionError("GC removed an unsafe or failed to delete the safe archive")

        # Recreate the previously deleted log from a byte-identical backup,
        # checking checksum and commit marker: basic data recoverability only.
        restored = owned / "restored" / "P200"
        restored.mkdir(parents=True)
        (restored / "data-0000.cq4").write_bytes(backup.read_bytes())
        restore_verified = (hashlib.sha256((restored / "data-0000.cq4").read_bytes()).hexdigest()
                            == source_digest)
        if not restore_verified or b"commit_seq=120" not in (restored/"data-0000.cq4").read_bytes():
            raise AssertionError("backup byte restore failed")
        report = {
            "schema":"otc-isolated-archive-gc-canary-v1",
            "executedAtUtc":datetime.now(timezone.utc).isoformat(),
            "mode":"DISPOSABLE_TEST_ONLY_ACTUAL_DELETE",
            "actualDeletedArchives":1,
            "canaryArchivedFilesDeleted":1,
            "unsafeArchivesPreserved":1,
            "negativeGatesRejected":rejected,
            "backupSha256":source_digest,
            "canaryBackupRestoreVerified":restore_verified,
            "liveOrderOrTradeArchivesTouched":False,
            "realChronicleBusinessRestoreProven":False,
            "productionGcEnabled":False,
            "nextGate":"trusted production watermark/backup/reader attestors and real CQ replay",
        }
    evidence_file.parent.mkdir(parents=True,exist_ok=True)
    with evidence_file.open("x",encoding="utf8") as stream:
        json.dump(report,stream,indent=2,ensure_ascii=False)
        stream.write("\n")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-canary",action="store_true",required=True)
    parser.add_argument("--report",type=Path,required=True)
    options=parser.parse_args(argv)
    result=execute_canary(options.report)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
