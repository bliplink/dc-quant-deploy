#!/usr/bin/env python3
"""T226 Trade P178 exact signed 1250 quorum-ledger head recovery.

Both real nodes are stopped; unsigned 1251 is retained as immutable forensic
evidence, NEVER installed/ACKed. Does not perform automatic HA promotion.
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

ROOT=Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready/TradeSvr")
EVIDENCE=Path("/Users/kong/.opentradingcore/trade-ha-forensics")
COMMITTED=1250
UNCOMMITTED=1251
NAMES=("dc-saas-tradesvr","dc-saas-tradesvr-b")

def epoch(node):
    n="TradeSvr"+node
    return ROOT/n/"TradeSvr"/n/"P178"/"epoch-2"

def sha(data):return hashlib.sha256(data).hexdigest()

def frames(data):
    at=0;out=[]
    while at<len(data):
        if at+28>len(data):raise RuntimeError("TRADE_P178_TRUNCATED_WAL")
        magic,e,s,length,crc=struct.unpack(">iqqii",data[at:at+28])
        if magic!=0x43425731 or e!=2 or s!=len(out)+1 or length<=0 or length>1048576 or at+28+length>len(data):
            raise RuntimeError("TRADE_P178_INVALID_FRAME")
        payload=data[at+28:at+28+length]
        if zlib.crc32(struct.pack(">qq",e,s)+payload)&0xffffffff!=crc&0xffffffff:
            raise RuntimeError("TRADE_P178_BAD_CRC")
        at+=28+length
        out.append((s,at,payload))
    return out

def certified_head(path,ledger=False):
    b=path.read_bytes()
    if len(b)<85:raise RuntimeError("P178_SIGNED_HEAD_TOO_SMALL")
    if struct.unpack(">i",b[:4])[0] != (0x4f545243 if ledger else 0x4f544343):
        raise RuntimeError("P178_CERTIFICATE_MAGIC_MISMATCH")
    off=8;length=struct.unpack(">H",b[off:off+2])[0];off+=2
    membership=b[off:off+length].decode();off+=length
    first,second=struct.unpack(">qq",b[off:off+16]);off+=16
    seq,epoch=(second,first) if ledger else (first,second)
    length=struct.unpack(">H",b[off:off+2])[0];off+=2
    signed_sha=b[off:off+length].decode()
    if epoch!=2 or not re.fullmatch("[a-f0-9]{64}",signed_sha):
        raise RuntimeError("P178_SIGNED_HEAD_INVALID")
    return seq,signed_sha,membership

def state():
    raw=json.loads(subprocess.check_output(["docker","inspect",*NAMES],text=True,timeout=20))
    return {i["Name"].lstrip("/"):i["State"]["Status"] for i in raw}

def zk():
    cmd="/apache-zookeeper-3.8.4-bin/bin/zkCli.sh -server 127.0.0.1:32181 2>/dev/null"
    text="get /dc/cluster/tradesvr/partitions/P178\nls /otc/demo-t181-fresh-20261027/trade/leases\nquit\n"
    r=subprocess.run(["docker","exec","-i","dc-saas-zookeeper","sh","-lc",cmd],
                     input=text,text=True,capture_output=True,timeout=25,check=True)
    items=[json.loads(x) for x in r.stdout.splitlines() if x.startswith('{"partitionId":"P178"')]
    if len(items)!=1:raise RuntimeError("P178_ZK_ASSIGNMENT_MISSING")
    obj=items[0]
    if obj.get("epoch")!=2 or obj.get("assignmentVersion")!=2 or obj.get("state")!="READY" or obj.get("primary")!="TradeSvrA" or obj.get("replica")!="TradeSvrB":
        raise RuntimeError("P178_ZK_OWNER_CHANGED")
    leases=[x.strip() for x in r.stdout.splitlines()
            if re.fullmatch(r'\[(?:TradeSvr[AB](?:, TradeSvr[AB])*)?\]',x.strip())]
    if len(leases)!=1:raise RuntimeError("P178_ZK_LEASES_UNKNOWN "+str(leases))
    return obj,leases[0]

def require_fenced():
    st=state()
    if any(st.get(n)!="exited" for n in NAMES):
        raise RuntimeError("P178_BOTH_TRADE_PROCESSES_MUST_STOP "+str(st))
    assignment,leases=zk()
    if leases!="[]":raise RuntimeError("P178_OLD_ZK_LEASE_STILL_PRESENT "+leases)
    return assignment

def write(path,data):
    with open(path,"xb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())

def fsync_dir(path):
    fd=os.open(str(path),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def atomic_replace(path,content):
    with tempfile.NamedTemporaryFile(prefix=".t226-certified-",dir=str(path.parent),delete=False) as f:
        f.write(content);f.flush();os.fsync(f.fileno());new=Path(f.name)
    os.replace(new,path)
    fsync_dir(path.parent)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    a,b=epoch("A"),epoch("B")
    aw,bw=(a/"business.wal").read_bytes(),(b/"business.wal").read_bytes()
    afr,bfr=frames(aw),frames(bw)
    if aw!=bw or len(afr)!=UNCOMMITTED or len(bfr)!=UNCOMMITTED:
        raise RuntimeError("P178_DUAL_IDENTICAL_UNCERTIFIED_TAIL_NOT_FOUND")
    tail=afr[-1][2].decode().split("\t")
    if len(tail)!=7 or base64.b64decode(tail[3]).decode()!="STATE_BATCH" or base64.b64decode(tail[4]).decode()!="1564963397655662592:Newing":
        raise RuntimeError("P178_DIRTY_BUSINESS_FRAME_NOT_EXPECTED")
    prefix=aw[:afr[COMMITTED-1][1]]
    signed=sha(prefix)
    a_head,a_sha,a_members=certified_head(a/"custody/head.bin")
    b_head,b_sha,b_members=certified_head(b/"custody/head.bin")
    a_ledger,a_ledger_sha,a_ledger_members=certified_head(a/"custody-ledger/receipt-quorum.bin",True)
    b_ledger,b_ledger_sha,b_ledger_members=certified_head(b/"custody-ledger/receipt-quorum.bin",True)
    if not (a_head==UNCOMMITTED and a_sha==sha(aw) and b_head==COMMITTED
            and b_sha==signed and a_ledger==b_ledger==COMMITTED
            and a_ledger_sha==b_ledger_sha==signed
            and a_members==b_members==a_ledger_members==b_ledger_members):
        raise RuntimeError("P178_AUTHORITY_NOT_JOINT_CERTIFIED_1250")
    ai=sorted(int(x.stem.split("-")[1]) for x in (a/"commit-index").glob("commit-*.bin"))
    bi=list((b/"commit-index").glob("commit-*.bin"))
    if ai!=list(range(1,UNCOMMITTED+1)) or bi:
        raise RuntimeError("P178_SIGNED_COMMIT_INDEX_UNEXPECTED")
    for i in range(256):
        if i==178:continue
        part="P%03d"%i
        x=ROOT/"TradeSvrA"/"TradeSvr"/"TradeSvrA"/part/"epoch-2/business.wal"
        y=ROOT/"TradeSvrB"/"TradeSvr"/"TradeSvrB"/part/"epoch-2/business.wal"
        if x.read_bytes()!=y.read_bytes():
            raise RuntimeError("P178_OTHER_SHARD_DIVERGED_"+part)
    assignment,leases=zk()
    if args.apply:assignment=require_fenced()
    print("P178_PREFLIGHT_PASS dual_frames=1251 durable_both_custody_quorum=1250 "
          "uncertified=1251 source_SHA256={} signed1250_SHA256={} leases={}".format(
              sha(aw),signed,leases))
    if not args.apply:
        print("DRY_RUN_NO_MUTATION")
        return
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    directory=EVIDENCE/("T226-P178-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    directory.mkdir(mode=0o700,exist_ok=False)
    for node,folder,data in (("A",a,aw),("B",b,bw)):
        write(directory/("TradeSvr"+node+"-original-1251.wal"),data)
        for rel in ("custody/head.bin","custody-ledger/receipt-quorum.bin"):
            write(directory/(node+"-"+rel.replace("/","-")),(folder/rel).read_bytes())
    archive=directory/"TradeSvrA-commit-index-1251.tar"
    with tarfile.open(str(archive),"w") as tar:
        for f in sorted((a/"commit-index").glob("commit-*.bin")):
            tar.add(str(f),arcname=f.name,recursive=False)
    manifest=dict(type="OPERATOR_MANUAL_RECOVERY_NOT_HA_PASS",partition="P178",
                  epoch=2,committed_both_custody=1250,uncommitted_frame=1251,
                  original_sha256=sha(aw),restored_sha256=signed,
                  A_Custody_at_1251=True,B_Custody_at_1250=True,
                  both_Quorum_Ledgers_at_1250=True,zk_assignment=assignment,
                  archived_index=True,timestamp=datetime.now().isoformat())
    write(directory/"manifest.json",json.dumps(manifest,indent=2).encode())
    fsync_dir(directory)
    if (a/"business.wal").read_bytes()!=aw or (b/"business.wal").read_bytes()!=bw:
        raise RuntimeError("P178_WAL_CHANGED_DURING_EVIDENCE")
    require_fenced()
    # Both nodes are OFFLINE. No customer ACK existed for seq1251.
    atomic_replace(a/"business.wal",prefix)
    atomic_replace(b/"business.wal",prefix)
    atomic_replace(a/"custody/head.bin",(b/"custody/head.bin").read_bytes())
    newest=a/"commit-index"/("commit-%020d.bin"%UNCOMMITTED)
    if not newest.exists():raise RuntimeError("P178_EXPECTED_UNACKED_CERT_INDEX_ABSENT")
    newest.unlink()
    fsync_dir(a/"commit-index")
    if (a/"business.wal").read_bytes()!=prefix or (b/"business.wal").read_bytes()!=prefix:
        raise RuntimeError("P178_POST_REPAIR_SIGNED_WAL_MISMATCH")
    print("P178_SIGNED_QUORUM_1250_INSTALLED forensic_evidence="+str(directory))

if __name__=="__main__":main()
