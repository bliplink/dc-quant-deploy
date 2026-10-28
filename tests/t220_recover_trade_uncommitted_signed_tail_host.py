#!/usr/bin/env python3
"""T220 Demo-only, evidence-first removal of ONE rejected, uncertified Trade WAL tail.

This is an operator intervention, NOT automatic failover acceptance. It refuses
a signed-prefix divergence, unknown mutation, live A writer, unmatched RSA head,
or Order acceptance. Preserve original bytes before atomic replacement.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready/TradeSvr")
EVIDENCE = Path("/Users/kong/.opentradingcore/trade-ha-forensics")
EXPECTED_REJECTED_KEY = "1564948443099631616:Newing"
EXPECTED_REJECTED_LOG = "order:1564948443099631616 execType:Newing success:false code:1003"


def epoch(node):
    name = "TradeSvr" + node
    return ROOT / name / "TradeSvr" / name / "P246" / "epoch-2"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def frames(value):
    at = 0
    out = []
    while at < len(value):
        if at + 28 > len(value):
            raise RuntimeError("partial WAL frame")
        magic, epoch_id, seq, length, checksum = struct.unpack(">iqqii", value[at:at + 28])
        if magic != 0x43425731 or epoch_id != 2 or length < 0 or at + 28 + length > len(value):
            raise RuntimeError("invalid WAL frame bounds")
        out.append((seq, value[at + 28:at + 28 + length]))
        at += 28 + length
    if any(seq != i + 1 for i, (seq, _) in enumerate(out)):
        raise RuntimeError("noncontiguous WAL sequence")
    return out


def write_evidence(path, content):
    with open(path, "xb") as writer:
        writer.write(content)
        writer.flush()
        os.fsync(writer.fileno())


def require_offline_recovery_window():
    # Dev-only maintenance fence: the ZooKeeper manifest must still name the
    # fully stopped A as P246 owner, with NO live A session. A B takeover or
    # assignment change aborts before touching the WAL.
    commands = (
        "get /dc/cluster/tradesvr/partitions/P246\n"
        "ls /otc/demo-t181-fresh-20261027/trade/leases\n"
        "quit\n"
    )
    script = ("/apache-zookeeper-3.8.4-bin/bin/zkCli.sh"
              " -server 127.0.0.1:32181 2>/dev/null")
    result = subprocess.run(
        ["docker", "exec", "-i", "dc-saas-zookeeper", "sh", "-lc", script],
        input=commands, text=True, capture_output=True, timeout=20, check=True)
    manifest_lines = [line for line in result.stdout.splitlines()
                      if line.startswith('{"partitionId":"P246"')]
    lease_lines = [line.strip() for line in result.stdout.splitlines()
                   if line.strip().startswith("[TradeSvr")]
    if len(manifest_lines) != 1 or lease_lines != ["[TradeSvrB]"]:
        raise RuntimeError("ZK recovery window not fenced or lease changed")
    assignment = json.loads(manifest_lines[0])
    if (assignment.get("epoch") != 2
            or assignment.get("assignmentVersion") != 2
            or assignment.get("primary") != "TradeSvrA"
            or assignment.get("replica") != "TradeSvrB"
            or assignment.get("state") != "READY"):
        raise RuntimeError("P246 membership or owner changed")
    return assignment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Execute after mandatory read-only preflight")
    options = parser.parse_args()
    a, b = epoch("A"), epoch("B")
    inspections = json.loads(subprocess.check_output(
        ["docker", "inspect", "dc-saas-tradesvr", "dc-saas-tradesvr-b"], text=True))
    states = {x["Name"].lstrip("/"): x["State"]["Status"] for x in inspections}
    if states.get("dc-saas-tradesvr") != "exited" or states.get("dc-saas-tradesvr-b") != "running":
        raise RuntimeError("A must be stopped and certified B must be running: " + str(states))
    assignment = require_offline_recovery_window()
    original = (a / "business.wal").read_bytes()
    certified = (b / "business.wal").read_bytes()
    af, bf = frames(original), frames(certified)
    if len(af) != len(bf) + 1 or not original.startswith(certified):
        raise RuntimeError("A is not an exact one-frame extension of B")
    for filename in ("custody/head.bin", "custody-ledger/receipt-quorum.bin"):
        if (a / filename).read_bytes() != (b / filename).read_bytes():
            raise RuntimeError("physical RSA custody differs: " + filename)
    commits = list((a / "commit-index").glob("commit-*.bin"))
    committed_sequences = sorted(int(path.stem.split('-')[1]) for path in commits)
    if committed_sequences != list(range(1, len(bf) + 1)):
        raise RuntimeError("A certified commit-index does not exactly match B WAL 1..N")
    payload = af[-1][1].decode("utf-8").split("\t")
    if len(payload) != 7 or base64.b64decode(payload[4]).decode() != EXPECTED_REJECTED_KEY:
        raise RuntimeError("unexpected uncertified Trade tail mutation")
    logs = subprocess.run(
        ["docker", "logs", "dc-saas-ordersvr-b"], capture_output=True, text=True).stdout
    if EXPECTED_REJECTED_LOG not in logs:
        raise RuntimeError("no independent proof that Order rejected uncertified command")
    print("PREFLIGHT_PASS A_frames={} certified_B_frames={} A_SHA256={} B_SHA256={}".format(
        len(af), len(bf), digest(original), digest(certified)))
    if not options.apply:
        print("DRY_RUN_NO_CHANGES")
        return
    evidence = EVIDENCE / ("T220-P246-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    evidence.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_evidence(evidence / "TradeSvrA-original-uncertified-tail.wal", original)
    write_evidence(evidence / "TradeSvrB-authoritative-certified-prefix.wal", certified)
    for filename in ("custody/head.bin", "custody-ledger/receipt-quorum.bin"):
        write_evidence(evidence / ("A-" + Path(filename).name), (a / filename).read_bytes())
        write_evidence(evidence / ("B-" + Path(filename).name), (b / filename).read_bytes())
    manifest = {
        "type": "DEMO_OPERATOR_REPAIR_NOT_AUTOMATIC_HA_PASS",
        "partition": "P246", "epoch": 2,
        "originalAFrames": len(af), "certifiedBFrames": len(bf),
        "originalASHA256": digest(original), "certifiedBSHA256": digest(certified),
        "rejectedOrder": EXPECTED_REJECTED_KEY,
        "rejectedOrderEvidence": EXPECTED_REJECTED_LOG,
        "certifiedCustodyAEqualsB": True, "timestamp": datetime.datetime.now().isoformat()
        , "zkAssignmentAtPreflight": assignment
    }
    write_evidence(evidence / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    folder = os.open(str(evidence), os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    if (a / "business.wal").read_bytes() != original or (b / "business.wal").read_bytes() != certified:
        raise RuntimeError("live WAL changed after evidence capture; STOP without modifying")
    if json.loads(subprocess.check_output(["docker", "inspect", "dc-saas-tradesvr"], text=True))[0]["State"]["Status"] != "exited":
        raise RuntimeError("Trade A became active, STOP")
    require_offline_recovery_window()
    with tempfile.NamedTemporaryFile(prefix=".t220-certified-prefix-", dir=str(a), delete=False) as tmp:
        tmp.write(certified)
        tmp.flush()
        os.fsync(tmp.fileno())
        staged = Path(tmp.name)
    os.replace(staged, a / "business.wal")
    folder = os.open(str(a), os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    if (a / "business.wal").read_bytes() != certified:
        raise RuntimeError("post-install signed-prefix verification failed")
    print("CERTIFIED_PREFIX_INSTALLED A_frames={} B_frames={} forensic_evidence={}".format(
        len(bf), len(bf), evidence))


if __name__ == "__main__":
    main()
