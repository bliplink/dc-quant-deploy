#!/usr/bin/env python3
"""Demo-only P119 recovery. Refuses live writers and preserves the uncertified tail.

This is a ONE-TIME operator repair, not automatic failover. Common must verify
the same archived dual-RSA custody independently when the new node boots.
"""
import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import tempfile
import zlib

ROOT = Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready/OrderSvr")
EVIDENCE = Path("/Users/kong/.opentradingcore/order-ha-forensics")
COMMITTED, UNCOMMITTED = 4104, 4105
SVC = ("dc-saas-ordersvr", "dc-saas-ordersvr-b")

def path(node):
    name = "OrderSvr" + node
    return ROOT / name / "OrderSvr" / name / "P119" / "epoch-2"

def sha(content):
    return hashlib.sha256(content).hexdigest()

def wal_frames(content):
    pos, result = 0, []
    while pos < len(content):
        if pos + 28 > len(content):
            raise RuntimeError("TRUNCATED_ORDER_WAL_FRAME")
        magic, epoch, seq, size, crc = struct.unpack(">iqqii", content[pos:pos + 28])
        if magic != 0x43425731 or epoch != 2 or size <= 0 or size > 1024 * 1024 or pos + 28 + size > len(content):
            raise RuntimeError("INVALID_ORDER_WAL_FRAME")
        payload = content[pos + 28:pos + 28 + size]
        if zlib.crc32(struct.pack(">qq", epoch, seq) + payload) & 0xffffffff != crc & 0xffffffff:
            raise RuntimeError("ORDER_WAL_CRC_MISMATCH")
        if seq != len(result) + 1:
            raise RuntimeError("ORDER_WAL_SEQUENCE_GAP")
        result.append((seq, payload))
        pos += 28 + size
    return result

def docker_states():
    items = json.loads(subprocess.check_output(["docker", "inspect", *SVC], text=True, timeout=20))
    return {it["Name"].lstrip("/"): it["State"]["Status"] for it in items}

def zk_window():
    cli = "/apache-zookeeper-3.8.4-bin/bin/zkCli.sh -server 127.0.0.1:32181 2>/dev/null"
    request = ("get /dc/cluster/ordersvr/partitions/P119\n"
               "ls /otc/demo-t181-fresh-20261027/order/leases\nquit\n")
    result = subprocess.run(["docker", "exec", "-i", "dc-saas-zookeeper", "sh", "-lc", cli],
                            input=request, text=True, capture_output=True, timeout=25, check=True)
    manifests = [json.loads(line) for line in result.stdout.splitlines()
                 if line.startswith('{"partitionId":"P119"')]
    if len(manifests) != 1:
        raise RuntimeError("ZK_P119_SIGNED_ASSIGNMENT_UNKNOWN")
    a = manifests[0]
    if (a.get("epoch") != 2 or a.get("assignmentVersion") != 2
            or a.get("primary") != "OrderSvrB"
            or a.get("replica") != "OrderSvrA"
            or a.get("state") != "READY"):
        raise RuntimeError("ZK_P119_ASSIGNMENT_CHANGED")
    lease_candidates = [line.strip() for line in result.stdout.splitlines()
                        if re.fullmatch(r'\[(?:OrderSvr[AB](?:, OrderSvr[AB])*)?\]', line.strip())]
    if len(lease_candidates) != 1:
        raise RuntimeError("ZK_LEASE_CENSUS_UNKNOWN " + str(lease_candidates))
    return a, lease_candidates[0]

def fsync_write(path, content):
    with open(path, "xb") as dst:
        dst.write(content)
        dst.flush()
        os.fsync(dst.fileno())

def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def require_stopped():
    states = docker_states()
    if any(states.get(s) != "exited" for s in SVC):
        raise RuntimeError("ORDER_BOTH_PHYSICAL_NODES_MUST_BE_STOPPED: " + str(states))
    assignment, leases = zk_window()
    if leases != "[]":
        raise RuntimeError("ORDER_ZK_PHYSICAL_LEASE_STILL_LIVE: " + leases)
    return assignment

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="off-line guarded atomic install")
    opts = parser.parse_args()
    a, b = path("A"), path("B")
    original_a, original_b = (a / "business.wal").read_bytes(), (b / "business.wal").read_bytes()
    af, bf = wal_frames(original_a), wal_frames(original_b)
    if len(af) != COMMITTED or len(bf) != UNCOMMITTED or not original_b.startswith(original_a):
        raise RuntimeError("P119_EXPECTED_CERTIFIED_PREFIX_VS_DIRTY_TAIL_CHANGED")
    tail_fields = bf[-1][1].split(b"\t")
    if len(tail_fields) != 7:
        raise RuntimeError("P119_UNCERTIFIED_TAIL_FORMAT_MISMATCH")
    tail_type = base64.b64decode(tail_fields[3]).decode()
    tail_id = base64.b64decode(tail_fields[4]).decode()
    if (tail_type, tail_id) not in {
            ("STATE_REMOVE", "1564964272058994688"),
            ("STATE_UPSERT", "1564982403624144896") }:
        raise RuntimeError("P119_UNCERTIFIED_TAIL_NOT_EXACT_KNOWN_REJECTED_COMMAND")
    if len(list((a / "commit-index").glob("commit-*.bin"))) != 0:
        raise RuntimeError("P119_REPLICA_UNEXPECTED_COMMIT_INDEX")
    committed_names = sorted(
        int(p.stem.split("-")[1]) for p in (b / "commit-index").glob("commit-*.bin"))
    if committed_names != list(range(1, COMMITTED + 1)):
        raise RuntimeError("P119_PRIMARY_COMMIT_INDEX_NOT_EXACT_1_TO_4104")
    artifacts = {}
    for name in ("custody/head.bin", "custody-ledger/receipt-quorum.bin"):
        aa, bb = (a / name).read_bytes(), (b / name).read_bytes()
        if not aa or aa != bb:
            raise RuntimeError("P119_RSA_CUSTODY_HEAD_DIVERGED: " + name)
        artifacts[name] = aa
    for i in range(256):
        if i == 119:
            continue
        shard = "P%03d" % i
        other = ROOT / "OrderSvrA" / "OrderSvr" / "OrderSvrA" / shard / "epoch-2" / "business.wal"
        other_b = ROOT / "OrderSvrB" / "OrderSvr" / "OrderSvrB" / shard / "epoch-2" / "business.wal"
        if other.read_bytes() != other_b.read_bytes():
            raise RuntimeError("OTHER_PARTITION_HAS_WAL_DIVERGENCE: " + shard)
    assignment, leases = zk_window()
    if opts.apply:
        require_stopped()
    print("P119_PREFLIGHT_PASS A_certified=4104 B_total=4105 B_uncommitted=1 "
          "A_SHA256={} B_SHA256={} ZK_leases={} apply={}".format(
              sha(original_a), sha(original_b), leases, opts.apply))
    if not opts.apply:
        print("DRY_RUN_NO_MUTATION")
        return
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    destination = EVIDENCE / ("T225-P119-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    destination.mkdir(mode=0o700, exist_ok=False)
    fsync_write(destination / "OrderSvrA-authoritative-4104.wal", original_a)
    fsync_write(destination / "OrderSvrB-original-4105-uncertified-tail.wal", original_b)
    for name, data in artifacts.items():
        fsync_write(destination / ("A-" + Path(name).name), data)
        fsync_write(destination / ("B-" + Path(name).name), data)
    archive = destination / "OrderSvrB-commit-index-4104.tar"
    with tarfile.open(str(archive), "w") as tar:
        for entry in sorted((b / "commit-index").glob("commit-*.bin")):
            tar.add(str(entry), arcname=entry.name, recursive=False)
    with open(archive, "rb") as handle:
        os.fsync(handle.fileno())
    manifest = {
        "type": "OPERATOR_MANUAL_DEMO_RECOVERY_NOT_AUTOMATIC_HA_PASS",
        "partition": "P119", "epoch": 2,
        "replicaA_framed": COMMITTED, "primaryB_original_framed": UNCOMMITTED,
        "primaryB_certified_commit_index": COMMITTED,
        "A_sha256": sha(original_a), "B_sha256": sha(original_b),
        "signed_custody_A_equals_B": True,
        "zk_assignment": assignment,
        "last_B_frame_type": tail_type + "_NOT_COMMITTED",
        "last_B_event_id": tail_id,
        "timestamp": datetime.now().isoformat()
    }
    fsync_write(destination / "manifest.json", json.dumps(manifest, indent=2).encode())
    fsync_dir(destination)
    if (a / "business.wal").read_bytes() != original_a or (b / "business.wal").read_bytes() != original_b:
        raise RuntimeError("P119_WAL_CHANGED_AFTER_FORENSIC_BACKUP")
    require_stopped()
    with tempfile.NamedTemporaryFile(prefix=".t225-signed-prefix-", dir=str(b), delete=False) as stage:
        stage.write(original_a)
        stage.flush()
        os.fsync(stage.fileno())
        temp = Path(stage.name)
    os.replace(temp, b / "business.wal")
    fsync_dir(b)
    if (b / "business.wal").read_bytes() != original_a:
        raise RuntimeError("P119_POST_INSTALL_CERTIFIED_PREFIX_CHANGED")
    print("CERTIFIED_P119_4104_PREFIX_INSTALLED_FOR_B forensic_evidence=" + str(destination))

if __name__ == "__main__":
    main()
