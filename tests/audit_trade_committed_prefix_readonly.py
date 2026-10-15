#!/usr/bin/env python3
"""Fail-closed read-only CQ *encoded-text* prefix comparison, NOT a Quorum/READY grant.

Every candidate record is extracted from one exact Chronicle text envelope.
The underlying physical CQ header/index/durability is NOT authenticated here.
This cannot authorize snapshot installation, archive deletion, or promotion.
"""
import argparse
import base64
import hashlib
import json
import mmap
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

PARTITION = re.compile(r"P[0-9]{3}\Z")


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing snapshot " + str(path))
    value = path.read_bytes()
    return json.loads(value), hashlib.sha256(value).hexdigest()


def properties(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing baseline")
    obj = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            obj[key.strip()] = val.strip()
    return obj


def scan_cq(path, partition, epoch, limit):
    """Return deterministic hashes plus commit metadata, never expose payload."""
    if path.is_symlink() or not path.is_file() or path.suffix != ".cq4":
        raise ValueError("unsafe or missing original CQ segment")
    start = base64.b64encode(partition.encode()) + b"\t" + str(epoch).encode() + b"\t"
    pattern = re.compile(re.escape(start)
        + rb"(?P<seq>[0-9]{1,12})\t(?P<kind>[A-Za-z0-9+/=]+)\t"
        + rb"(?P<id>[A-Za-z0-9+/=]*)\t[0-9]{10,20}\t(?P<payload>[A-Za-z0-9+/=]*)")
    rows = {}
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for match in pattern.finditer(mm):
            seq = int(match.group("seq"))
            if seq < 1 or seq > limit:
                continue
            if seq in rows:
                raise ValueError("duplicate encoded CQ logical sequence")
            try:
                kind = base64.b64decode(match.group("kind"), validate=True).decode("utf-8")
                event_id = base64.b64decode(match.group("id"), validate=True).decode("utf-8")
                if kind not in ("STATE_BATCH", "STATE_COMMIT"):
                    continue
                # The regex runs over binary Chronicle CQ storage, not a
                # delimited text file. Bytes in the next CQ header may also
                # be base64 alphabet characters; use canonical JSON envelope
                # validation to find the exact payload terminus. Never hash
                # an ambiguous candidate or assume an arbitrary suffix.
                encoded = match.group("payload")
                candidates = []
                for trailing in range(0, 4):
                    trimmed = encoded[:-trailing] if trailing else encoded
                    if len(trimmed) % 4: continue
                    try:
                        decoded = base64.b64decode(trimmed, validate=True)
                        parsed = json.loads(decoded)
                        if not isinstance(parsed, dict): continue
                        if base64.b64encode(decoded) != trimmed: continue
                        candidates.append((trailing, trimmed, parsed))
                    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                        continue
                if len(candidates) != 1:
                    continue
                trailing, trimmed, parsed = candidates[0]
                envelope = match.group(0)[:-trailing] if trailing else match.group(0)
                payload = parsed if kind == "STATE_COMMIT" else None
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                # Reject a partial match inside CQ binary metadata; require
                # the full contiguous committed seq set after scanning.
                continue
            rows[seq] = {"sha": hashlib.sha256(envelope).digest(),
                         "kind": kind, "eventId": event_id, "commit": payload}
    return rows


def digest_prefix(rows, head):
    if len(rows) < head or any(x not in rows for x in range(1, head+1)):
        return None
    h = hashlib.sha256()
    for seq in range(1, head+1):
        h.update(seq.to_bytes(8, "big") + rows[seq]["sha"])
    return h.hexdigest()


def audit_partition(root, part):
    if not PARTITION.fullmatch(part):
        raise ValueError("invalid partition")
    source_root = root / "TradeSvrA"
    replica_root = root / "TradeSvrB"
    snap_file = source_root / "snapshot" / part / "latest.json"
    snapshot, snapshot_sha = read_json(snap_file)
    base = properties(source_root / "journal" / part / "baseline.properties")
    epoch = int(snapshot.get("epoch", 0))
    head = int(snapshot.get("snapshotSeq", 0))
    state_seq = int(snapshot.get("committedStateSeq", -1))
    state_epoch = int(snapshot.get("committedStateEpoch", -1))
    if snapshot.get("partitionId") != part or epoch < 1 or head < 2 \
            or state_seq != head-1 or state_epoch != epoch \
            or int(base.get("commitMarkerSeq", -1)) != head \
            or int(base.get("committedStateSeq", -1)) != state_seq \
            or int(base.get("epoch", -1)) != epoch or int(base.get("baselineSeq", -1)) != head:
        raise ValueError("primary Snapshot / committed journal baseline disagreement")
    arc_root = source_root / "journal" / ".archive"
    if arc_root.is_symlink() or not arc_root.is_dir():
        raise ValueError("missing or unsafe immutable source archive")
    dirs = sorted((d for d in arc_root.glob(part + "-epoch" + str(epoch) + "-*")
                   if d.is_dir() and not d.is_symlink()), key=lambda p:p.stat().st_mtime)
    selected, src = None, None
    for directory in dirs:
        segments = list(directory.glob("*.cq4"))
        if len(segments) != 1:
            continue
        candidate = scan_cq(segments[0], part, epoch, head+1)
        if candidate.get(head, {}).get("kind") == "STATE_COMMIT" \
                and digest_prefix(candidate, head) is not None:
            selected, src = directory, candidate
            break
    if selected is None:
        raise ValueError("no complete source archived committed WAL prefix")
    replica_files = list((replica_root / "journal" / part).glob("*.cq4"))
    if len(replica_files) != 1:
        raise ValueError("replica original Chronicle WAL missing or ambiguous")
    replica = scan_cq(replica_files[0], part, epoch, head+1)
    replica_chain = digest_prefix(replica, head)
    source_chain = digest_prefix(src, head)
    head_src, head_rep = src[head], replica.get(head)
    if head_src["kind"] != "STATE_COMMIT" or head_rep is None:
        raise ValueError("source or replica signed head marker unavailable")
    marker = head_src["commit"]
    if not isinstance(marker, dict) or marker.get("stateSeq") != state_seq \
            or marker.get("stateEpoch") != state_epoch \
            or marker.get("stateEventId") != src[head-1]["eventId"] \
            or src[head-1]["kind"] != "STATE_BATCH":
        raise ValueError("committed head does not link back to STATE_BATCH")
    if any(src[k]["sha"] != replica[k]["sha"] for k in range(1, head+1) if k in replica):
        mismatched = True
    else:
        mismatched = False
    tail_src = src.get(head+1)
    tail_rep = replica.get(head+1)
    snap_after, sha_after = read_json(snap_file)
    if sha_after != snapshot_sha or snap_after != snapshot:
        raise ValueError("primary Snapshot changed during audit")
    equal = source_chain is not None and source_chain == replica_chain and not mismatched
    return {"partition":part,"epoch":epoch,"committedMarkerSeq":head,
            "committedStateSeq":state_seq,"snapshotSha256":snapshot_sha,
            "sourceArchiveSegments":len(dirs),"sourceArchive":selected.name,
            "sourceCommittedRecords":head,"replicaCommittedRecords":len([s for s in replica if s<=head]),
            "committedPrefixCompleteAndEqual":bool(equal),
            "committedPrefixSha256":source_chain if equal else None,
            "nextUncommittedSeq":head+1,
            "nextUncommittedRawTextConflicts":bool(tail_src and tail_rep and tail_src["sha"]!=tail_rep["sha"]),
            "independentPhysicalQuorumVerified":False,"authorizesReady":False,
            "authorizesReplicaInstall":False,"authorizesWalDeletion":False}


def audit(root, partitions):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("unsafe or missing data root")
    if not partitions or len(partitions)!=len(set(partitions)):
        raise ValueError("nonempty unique partitions required")
    rows = [audit_partition(root,p) for p in partitions]
    return {"schema":"otc-trade-readonly-committed-prefix-v1",
            "capturedUtc":datetime.now(timezone.utc).isoformat(),
            "readOnly":True,"rows":rows,
            "allLocalCommittedPrefixesEqual":all(x["committedPrefixCompleteAndEqual"] for x in rows),
            "decision":"EVIDENCE_ONLY_NO_CERTIFIED_READY",
            "signedSourceHeadVerified":False,"independentPhysicalQuorumVerified":False,
            "authorizesReady":False,"authorizesReplicaInstall":False,
            "authorizesWalDeletion":False,
            "caveat":"Read-only Chronicle text envelope hashes, not complete CQ frame validation, signed source HEAD, independent quorum or business reconciliation."}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root",required=True,type=Path)
    p.add_argument("--partitions",nargs="+",required=True)
    p.add_argument("--output",type=Path)
    a=p.parse_args(argv)
    try:
        report=audit(a.data_root,a.partitions)
        text=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
        if a.output:
            target=a.output.resolve(strict=False)
            if a.output.exists() or a.output.is_symlink() or a.data_root.resolve() in target.parents:
                raise ValueError("refusing to overwrite or write into live data root")
            a.output.parent.mkdir(parents=True,exist_ok=True)
            with a.output.open("x",encoding="utf-8") as io:io.write(text)
        print(text)
        return 0 if report["allLocalCommittedPrefixesEqual"] else 2
    except (OSError,ValueError,KeyError,TypeError,OverflowError,json.JSONDecodeError) as exc:
        print("TRADE_PREFIX_AUDIT_UNAVAILABLE: "+str(exc)[:240],file=sys.stderr)
        return 3

if __name__=="__main__":sys.exit(main())
