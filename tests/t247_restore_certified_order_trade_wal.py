#!/usr/bin/env python3
"""T247 Demo-only offline recovery to exact doubly certified WAL prefixes.

Dry-run by default. The --apply path is deliberately fenced: no Order/Trade
process may run, both ZooKeeper service leases must be absent, no other WAL
partition may differ, the paired RSA/Custody attestations and complete commit
indices must equal the shorter WAL. Preserve BOTH originals before change.
This is a maintenance repair, NOT automatic failover certification.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zlib

DATA = Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready")
FORENSICS = Path("/Users/kong/.opentradingcore/t247-certified-tail-forensics")
CASES = (("OrderSvr", 106, "A", 33892), ("OrderSvr", 142, "A", 23646),
         ("TradeSvr", 23, "B", 3364))
SERVICES = ("dc-saas-ordersvr", "dc-saas-ordersvr-b",
            "dc-saas-tradesvr", "dc-saas-tradesvr-b")
EXPECTED = {("OrderSvr", 106), ("OrderSvr", 142), ("TradeSvr", 23)}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def location(service, number, node):
    name = service + node
    return DATA / service / name / service / name / ("P%03d" % number) / "epoch-2"


def safe_read(path):
    require(path.is_file() and not path.is_symlink(), "missing/linked file: " + str(path))
    return path.read_bytes()


def frames(data):
    at, sequence = 0, 0
    while at < len(data):
        require(at + 28 <= len(data), "incomplete WAL frame")
        magic, epoch, seq, length, crc = struct.unpack_from(">IqqII", data, at)
        require(magic == 0x43425731 and epoch == 2 and seq == sequence + 1
                and 0 < length <= 1048576 and at + 28 + length <= len(data),
                "invalid WAL header/epoch/sequence")
        payload = data[at + 28:at + 28 + length]
        require(zlib.crc32(struct.pack(">qq", epoch, seq) + payload) == crc,
                "invalid WAL frame CRC")
        at += 28 + length
        sequence = seq
    return sequence


def parse_cert(data, ledger):
    at = 0
    def number(fmt):
        nonlocal at
        size = struct.calcsize(fmt)
        require(at + size <= len(data), "truncated custody")
        value = struct.unpack_from(fmt, data, at)[0]
        at += size
        return value
    def text():
        nonlocal at
        size = number(">H")
        require(at + size <= len(data), "truncated custody string")
        value = data[at:at + size].decode("utf-8")
        at += size
        return value
    magic = number(">I")
    version = number(">I")
    membership = text()
    first, second = number(">q"), number(">q")
    digest = text()
    votes = number(">i")
    require(magic == (0x4F545243 if ledger else 0x4F544343) and version == 1
            and votes == 2, "custody header/version/quorum mismatch")
    return (first if ledger else second), (second if ledger else first), digest, membership


def zk_state():
    commands = []
    for service, number, _, _ in CASES:
        commands.append("get /dc/cluster/%s/partitions/P%03d" % (service.lower(), number))
    for service in ("order", "trade"):
        commands.append("ls /otc/demo-t181-fresh-20261027/%s/leases" % service)
    commands.append("quit")
    result = subprocess.run(
        ["docker", "exec", "-i", "-e",
         "CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini",
         "dc-saas-zookeeper", "zkCli.sh", "-server", "127.0.0.1:32181"],
        input="\n".join(commands) + "\n", text=True, capture_output=True,
        check=True, timeout=45)
    output = result.stdout + result.stderr
    require("KeeperErrorCode" not in output, "ZooKeeper read error")
    rows = {}
    for line in output.splitlines():
        if line.startswith('{"partitionId":"P'):
            item = json.loads(line)
            rows[item["partitionId"], item["primary"].split("Svr")[0]] = item
    for service, number, owner, _ in CASES:
        item = json.loads(next(line for line in output.splitlines()
                               if line.startswith('{"partitionId":"P%03d"' % number)
                               and '"primary":"%s' % service in line))
        require(item.get("epoch") == 2 and item.get("assignmentVersion") == 2
                and item.get("primary") == service + owner and item.get("state") == "READY",
                "ZK assignment/owner changed " + service + str(number))
    leases = [line.strip() for line in output.splitlines()
              if re.fullmatch(r"\[(?:(?:Order|Trade)Svr[AB](?:, (?:Order|Trade)Svr[AB])*)?\]",
                              line.strip())]
    require(len(leases) == 2, "ZK lease census untrusted")
    return leases


def require_offline():
    states = json.loads(subprocess.check_output(["docker", "inspect", *SERVICES], text=True))
    require(all(row["State"]["Running"] is False for row in states), "live writer present")
    leases = zk_state()
    require(leases == ["[]", "[]"], "node lease still live: " + str(leases))


def inventory():
    result = {}
    for service, number, owner, seq in CASES:
        other = "B" if owner == "A" else "A"
        long_root, short_root = location(service, number, owner), location(service, number, other)
        long = safe_read(long_root / "business.wal")
        short = safe_read(short_root / "business.wal")
        require(long.startswith(short) and frames(long) == seq + 1 and
                frames(short) == seq, "expected exact one-frame uncertified tail")
        certificates = {}
        for node, base in ((owner, long_root), (other, short_root)):
            head = safe_read(base / "custody/head.bin")
            receipt = safe_read(base / "custody-ledger/receipt-quorum.bin")
            h_epoch, h_seq, h_hash, h_members = parse_cert(head, False)
            r_epoch, r_seq, r_hash, r_members = parse_cert(receipt, True)
            require(h_epoch == r_epoch == 2 and h_seq == r_seq == seq
                    and h_hash == r_hash == sha(short) and h_members == r_members,
                    "RSA/custody head does not attest precise prefix")
            certificates[node] = (head, receipt)
        require(certificates[owner] == certificates[other], "different signed custody across peers")
        commits = [int(file.stem.split("-")[1]) for file in (long_root / "commit-index").glob("commit-*.bin")]
        require(len(commits) == seq and len(set(commits)) == seq
                and min(commits) == 1 and max(commits) == seq,
                "owner CommitIndex is not exactly 1..signed HEAD")
        require(not list((short_root / "commit-index").glob("commit-*.bin")),
                "replica has unexpected CommitIndex")
        result[(service, number)] = dict(owner=owner, long=long, short=short,
                                         long_root=long_root, short_root=short_root,
                                         signatures=certificates, seq=seq)
    for service in ("OrderSvr", "TradeSvr"):
        for number in range(256):
            if (service, number) in EXPECTED:
                continue
            require(safe_read(location(service, number, "A") / "business.wal")
                    == safe_read(location(service, number, "B") / "business.wal"),
                    "another partition has changed P%03d" % number)
    return result


def durable_write(path, data):
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def fsync_dir(folder):
    descriptor = os.open(str(folder), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cases = inventory()
    print("T247_CERTIFIED_PREFIX_PREFLIGHT_PASS",
          {name + "_P%03d" % number: {"certified": item["seq"], "uncertified": 1}
           for (name, number), item in cases.items()})
    if not args.apply:
        print("DRY_RUN_NO_MUTATION")
        return
    require_offline()
    FORENSICS.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = FORENSICS / ("T247-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    destination.mkdir(mode=0o700, exist_ok=False)
    for (service, number), item in cases.items():
        tag = service + "-P%03d" % number
        durable_write(destination / (tag + "-original-uncertified.wal"), item["long"])
        durable_write(destination / (tag + "-exact-certified-prefix.wal"), item["short"])
        for node, (head, receipt) in item["signatures"].items():
            durable_write(destination / (tag + "-" + node + "-head.bin"), head)
            durable_write(destination / (tag + "-" + node + "-quorum.bin"), receipt)
    manifest = {
        "scope": "OFFLINE_OPERATOR_REPAIR_NOT_AUTOMATIC_HA_PASS",
        "cases": [{"service": service, "partition": "P%03d" % number,
                   "owner": item["owner"], "certifiedSeq": item["seq"],
                   "uncertifiedSha256": sha(item["long"]),
                   "certifiedSha256": sha(item["short"])}
                  for (service, number), item in cases.items()]}
    durable_write(destination / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    fsync_dir(destination)
    fsync_dir(FORENSICS)
    require_offline()
    updated = inventory()
    require(all(updated[key]["long"] == cases[key]["long"] and
                updated[key]["short"] == cases[key]["short"] for key in cases),
            "WAL changed during evidence capture")
    for (service, number), item in cases.items():
        folder = item["long_root"]
        with tempfile.NamedTemporaryFile(prefix=".t247-certified-prefix-", dir=str(folder), delete=False) as temp:
            temp.write(item["short"])
            temp.flush()
            os.fsync(temp.fileno())
            staged = Path(temp.name)
        os.replace(staged, folder / "business.wal")
        fsync_dir(folder)
        require(sha(safe_read(folder / "business.wal")) == sha(item["short"]),
                "installed prefix verification failed")
    print("T247_OFFLINE_RESTORE_PASS cases=3 all_original_bytes_preserved=true")
    print("FORENSICS:", destination)


if __name__ == "__main__":
    main()