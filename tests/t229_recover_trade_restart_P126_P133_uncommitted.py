#!/usr/bin/env python3
"""One-time Demo-only authenticated P126/P133 uncommitted tail rollback.

NOT automatic failover; operator requires both Trade JVMs stopped, no ZK lease,
verified dual identical physical custody AND receipt watermarks. Preserves every
original physical byte in an independently fsynced forensic directory.
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
import tempfile
import zlib

DATA=Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready/TradeSvr")
FORENSICS=Path("/Users/kong/.opentradingcore/trade-ha-forensics")
EXPECT={126:("A",3638,"1564989627067056128:Trade_Cancel"),
        133:("B",3031,"1564989565243015169:Trade_Cancel")}
CONTAINERS=("dc-saas-tradesvr","dc-saas-tradesvr-b")

def folder(node,partition):
    instance="TradeSvr"+node
    return DATA/instance/"TradeSvr"/instance/("P%03d"%partition)/"epoch-2"

def sha(data):return hashlib.sha256(data).hexdigest()
def assert_is(predicate,code):
    if not predicate:raise RuntimeError(code)

def parse_wal(data,partition):
    at=0;records=[]
    while at<len(data):
        assert_is(at+28<=len(data),"TRUNCATED_HEADER")
        magic,epoch,seq,length,crc=struct.unpack(">iqqii",data[at:at+28])
        assert_is(magic==0x43425731 and epoch==2 and seq==len(records)+1
                  and 0<length<=1048576 and at+28+length<=len(data),"FRAME_OR_EPOCH_CORRUPT")
        payload=data[at+28:at+28+length]
        assert_is(zlib.crc32(struct.pack(">qq",epoch,seq)+payload)&0xffffffff==crc&0xffffffff,"FRAME_CRC_CORRUPT")
        records.append((seq,at+28+length,payload))
        at+=28+length
    return records

def parse_head(data,ledger):
    expect_magic=0x4f545243 if ledger else 0x4f544343
    assert_is(struct.unpack(">i",data[:4])[0]==expect_magic,"SIGNATURE_EVIDENCE_MAGIC_MISMATCH")
    pos=8;length=struct.unpack(">H",data[pos:pos+2])[0];pos+=2
    membership=data[pos:pos+length].decode();pos+=length
    x,y=struct.unpack(">qq",data[pos:pos+16]);pos+=16
    epoch,seq=(x,y) if ledger else (y,x)
    length=struct.unpack(">H",data[pos:pos+2])[0];pos+=2
    hash_=data[pos:pos+length].decode()
    assert_is(epoch==2 and re.fullmatch("[a-f0-9]{64}",hash_) is not None,"INVALID_HEAD")
    return membership,seq,hash_

def zk():
    script="/apache-zookeeper-3.8.4-bin/bin/zkCli.sh -server 127.0.0.1:32181 2>/dev/null"
    request="ls /otc/demo-t181-fresh-20261027/trade/leases\n"
    for p in EXPECT:request+="get /dc/cluster/tradesvr/partitions/P%03d\n"%p
    request+="quit\n"
    result=subprocess.run(["docker","exec","-i","dc-saas-zookeeper","sh","-lc",script],
                          input=request,text=True,capture_output=True,check=True,timeout=25)
    rows=result.stdout.splitlines()
    leases=[x.strip() for x in rows if re.fullmatch(r'\[(?:TradeSvr[AB](?:, TradeSvr[AB])*)?\]',x.strip())]
    assert_is(len(leases)==1,"UNTRUSTED_ZK_LEASE_CENSUS")
    assignments={}
    for line in rows:
        if line.startswith('{"partitionId":"P'):
            data=json.loads(line)
            p=int(data["partitionId"][1:])
            if p not in EXPECT:continue
            primary,seq,req=EXPECT[p]
            assert_is(data.get("epoch")==2 and data.get("assignmentVersion")==2
                      and data.get("state")=="READY"
                      and data.get("primary")=="TradeSvr"+primary
                      and data.get("replica")=="TradeSvr"+("B" if primary=="A" else "A"),
                      "ZK_SIGNED_ASSIGNMENT_CHANGED")
            assignments[p]=data
    assert_is(set(assignments)==set(EXPECT),"MISSING_ZK_ASSIGNMENT")
    return leases[0],assignments

def require_offline():
    states={s["Name"].lstrip("/"):s["State"]["Status"]
            for s in json.loads(subprocess.check_output(["docker","inspect",*CONTAINERS],text=True))}
    assert_is(all(states.get(s)=="exited" for s in CONTAINERS),"TRADE_WRITER_STILL_RUNNING")
    lease,assignment=zk()
    assert_is(lease=="[]","TRADE_ZK_LEASE_STILL_ACTIVE "+lease)
    return assignment

def write_new(path,data):
    with open(path,"xb") as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())

def sync_dir(path):
    fd=os.open(str(path),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def repair():
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",help="offline forensic signed prefix rollback")
    args=parser.parse_args()
    result={};lease,assignments=zk()
    for part,(primary,headseq,last_event) in EXPECT.items():
        writer=folder(primary,part)
        replica=folder("B" if primary=="A" else "A",part)
        wal_w=(writer/"business.wal").read_bytes()
        wal_r=(replica/"business.wal").read_bytes()
        fw=parse_wal(wal_w,part);fr=parse_wal(wal_r,part)
        assert_is(len(fw)==headseq+1 and len(fr)==headseq and
                  wal_w.startswith(wal_r),"EXPECTED_ONLY_ONE_DIRTY_TAIL")
        assert_is(base64.b64decode(fw[-1][2].decode().split("\t")[4]).decode()==last_event,
                  "UNEXPECTED_UNCOMMITTED_BUSINESS_REQUEST")
        candidates={}
        for node in ("A","B"):
            root=folder(node,part)
            custody=(root/"custody/head.bin").read_bytes()
            ledger=(root/"custody-ledger/receipt-quorum.bin").read_bytes()
            cm,cseq,ch=parse_head(custody,False)
            lm,lseq,lh=parse_head(ledger,True)
            assert_is(cm==lm and cseq==lseq==headseq and ch==lh==sha(wal_r),
                      "UNVERIFIED_DUAL_SIGNED_RSA_CUSTODY_HEAD")
            candidates[node]=(custody,ledger)
        assert_is(candidates["A"]==candidates["B"],"PHYSICAL_CUSTODY_SIGNATURE_DIVERGENCE")
        commits=sorted(int(p.stem.split("-")[1]) for p in (writer/"commit-index").glob("commit-*.bin"))
        assert_is(commits==list(range(1,headseq+1)) and
                  not list((replica/"commit-index").glob("commit-*.bin")),
                  "PRIMARY_COMMIT_INDEX_NOT_EXACT_SIGNED_HEAD")
        result[part]=dict(primary=primary,seq=headseq,
                          uncommitted_sha=sha(wal_w),certified_sha=sha(wal_r),
                          writer=writer,replica=replica,writer_raw=wal_w,
                          replica_raw=wal_r,custody=candidates)
    for i in range(256):
        if i in EXPECT:continue
        x=(folder("A",i)/"business.wal").read_bytes()
        y=(folder("B",i)/"business.wal").read_bytes()
        assert_is(x==y,"OTHER_TRADE_PARTITION_DIVERGED_P%03d"%i)
    if args.apply:require_offline()
    print("T229_PREFLIGHT_PASS "+json.dumps(
        {p:{"primary":v["primary"],"signed_seq":v["seq"],
            "uncertified_sha":v["uncommitted_sha"],"certified_sha":v["certified_sha"]}
         for p,v in result.items()},sort_keys=True)+" zkLeases="+lease)
    if not args.apply:
        print("DRY_RUN_NO_MUTATION");return
    FORENSICS.mkdir(parents=True,exist_ok=True)
    dest=FORENSICS/("T229-Trade-P126-P133-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    dest.mkdir(mode=0o700,exist_ok=False)
    for part,data in result.items():
        write_new(dest/("P%03d-PRIMARY-original-uncertified.wal"%part),data["writer_raw"])
        write_new(dest/("P%03d-REPLICA-original-certified.wal"%part),data["replica_raw"])
        for node,(custody,ledger) in data["custody"].items():
            write_new(dest/("P%03d-%s-custody-head.bin"%(part,node)),custody)
            write_new(dest/("P%03d-%s-custody-ledger.bin"%(part,node)),ledger)
    write_new(dest/"manifest.json",json.dumps(
        dict(type="MANUAL_OFFLINE_UNACKED_TAIL_REMOVAL_NOT_AUTOMATIC_HA",
             partitions={str(k):{"old":v["uncommitted_sha"],
                                 "certified":v["certified_sha"],"seq":v["seq"]}
                         for k,v in result.items()},timestamp=datetime.now().isoformat(),
             assignments=assignments),indent=2).encode())
    sync_dir(dest)
    require_offline()
    for part,data in result.items():
        assert_is((data["writer"]/"business.wal").read_bytes()==data["writer_raw"]
                  and (data["replica"]/"business.wal").read_bytes()==data["replica_raw"],
                  "WAL_CHANGED_DURING_FORENSIC_ARCHIVE")
        destwal=data["writer"]/"business.wal"
        with tempfile.NamedTemporaryFile(prefix=".t229-signed-prefix-",dir=str(data["writer"]),delete=False) as f:
            f.write(data["replica_raw"]);f.flush();os.fsync(f.fileno());tmp=Path(f.name)
        os.replace(tmp,destwal);sync_dir(data["writer"])
        assert_is(destwal.read_bytes()==data["replica_raw"],"SIGNED_PREFIX_REPLACEMENT_FAILED")
    print("T229_BOTH_SIGNED_PREFIXES_RESTORED_EVIDENCE="+str(dest))

if __name__=="__main__":
    repair()
