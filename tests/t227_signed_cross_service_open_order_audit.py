#!/usr/bin/env python3
"""Read-only cross-service signed WAL projection audit; NEVER grants READY.

Compare Order's and Trade's active OPEN_ORDER IDs for each tenant after Common
replicas are byte-consistent. A/B equality alone cannot prove business saga
consistency. Never deletes orders, changes custody or performs recovery.
"""
import argparse
import base64
import collections
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT=Path("/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/data/common-t182-ready")
TARGETS={
    "WSI1WX":("P119","P178"),
    "U6ZAMX":("P210","P126"),
    "G6IQ8E":("P106","P133"),
    "R0F6CC":("P089","P246")
}

def frames(payload,part):
    offset=0
    seq=0
    while offset<len(payload):
        if offset+28>len(payload):raise RuntimeError("torn WAL header at "+part)
        magic,epoch,observed,size,checksum=struct.unpack(">iqqii",payload[offset:offset+28])
        if magic!=0x43425731 or epoch!=2 or observed!=seq+1 or not 0<size<=1048576 or offset+28+size>len(payload):
            raise RuntimeError("invalid WAL frame sequence/epoch at "+part)
        raw=payload[offset+28:offset+28+size]
        if zlib.crc32(struct.pack(">qq",epoch,observed)+raw)&0xffffffff!=checksum&0xffffffff:
            raise RuntimeError("WAL CRC mismatch at "+part)
        fields=raw.decode("utf-8").split("\t")
        if len(fields)!=7:raise RuntimeError("invalid domain WAL codec at "+part)
        identity=base64.b64decode(fields[0]).decode()
        if identity!=part:raise RuntimeError("wrong signed partition field")
        yield json.loads(base64.b64decode(fields[-1]))
        seq=observed;offset+=28+size

def read_wal(service,node,partition):
    p=ROOT/service/(service+node)/service/(service+node)/partition/"epoch-2/business.wal"
    return p.read_bytes()

def main():
    args=argparse.ArgumentParser()
    args.add_argument("--strict",action="store_true",help="exit 2 on persistent saga mismatch; never mutate")
    args.add_argument("--json",action="store_true",help="machine-readable audit evidence")
    opts=args.parse_args()
    output={}
    for location,(order_part,trade_part) in TARGETS.items():
        reconstructed={}
        divergent_replicas=[]
        for service,part in (("OrderSvr",order_part),("TradeSvr",trade_part)):
            a=read_wal(service,"A",part)
            b=read_wal(service,"B",part)
            if a!=b:divergent_replicas.append(service)
            # Only a byte-identical A/B candidate is accepted as consistent.
            # Otherwise do not choose an arbitrary authority.
            if divergent_replicas:continue
            active={}
            for event in frames(a,part):
                if service=="OrderSvr":
                    if event.get("location")!=location:continue
                    key=str(event["orderId"])
                    if event.get("operation")=="REMOVE":active.pop(key,None)
                    elif event.get("operation")=="UPSERT":active[key]=event.get("order") or {}
                else:
                    if event.get("location")!=location:continue
                    for mutation in event.get("mutations",[]):
                        if mutation.get("entityType")!="OPEN_ORDER":continue
                        key=mutation["entityKey"].split("\u001f")[-1]
                        if mutation.get("operation")=="REMOVE":active.pop(key,None)
                        elif mutation.get("operation")=="UPSERT":
                            active[key]=json.loads(mutation["payload"])
            reconstructed[service]=active
        old=set(reconstructed.get("OrderSvr",{}))
        trade=set(reconstructed.get("TradeSvr",{}))
        if divergent_replicas:
            state="PHYSICAL_WAL_RACE_RETRY"
        else:
            state="PASS" if old==trade else "CROSS_SERVICE_MISMATCH"
        output[location]={
            "state":state,
            "order_partition":order_part,
            "trade_partition":trade_part,
            "order_open":len(old),
            "trade_open":len(trade),
            "order_only":len(old-trade),
            "trade_only":len(trade-old),
            "order_only_example":sorted(old-trade)[:5],
            "trade_only_example":sorted(trade-old)[:5],
            "replica_mismatch":divergent_replicas,
        }
    if opts.json:print(json.dumps(output,indent=2,sort_keys=True))
    else:
        for loc,s in output.items():
            print("{} {} Order={} Trade={} OrderOnly={} TradeOnly={} examples={}".format(
                loc,s["state"],s["order_open"],s["trade_open"],
                s["order_only"],s["trade_only"],s["order_only_example"]))
    if opts.strict and any(row["state"]!="PASS" for row in output.values()):
        return 2
    return 0

if __name__=="__main__":
    sys.exit(main())
