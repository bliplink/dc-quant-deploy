#!/usr/bin/env python3
"""Prepare an *unready* initial Common ZK manifest for a NEW Demo namespace.

All 256 partitions are E1 RECOVERING, STRICT. This cannot authorize an
order, create an RSA receipt, publish READY or modify ZooKeeper. Only a
genuine first-boot signed E1/E2 workflow can activate it. No old namespace
or original born files are touched.
"""
import argparse
import hashlib
import pathlib
import sys

SERVICES = ("OrderSvr", "TradeSvr")

def manifest(service):
    if service not in SERVICES:
        raise ValueError("Unknown Common business service")
    lines=["NPC1|1"]
    for i in range(256):
        home=service+("A" if i<128 else "B")
        backup=service+("B" if i<128 else "A")
        lines.append(f"P{i:03d}|1|{home}|{backup}|STRICT_QUORUM|RECOVERING")
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args=parser.parse_args()
    if not args.namespace.startswith("/otc/t364-fresh-20261031-") or not args.namespace.endswith("/"):
        raise SystemExit("T364_NEEDS_NEW_INDEPENDENT_ZK_NAMESPACE")
    if args.output_dir.exists():
        raise SystemExit("T364_OUTPUT_ALREADY_EXISTS_NO_REUSE")
    args.output_dir.mkdir(parents=True)
    for service,layer in (("OrderSvr","order"),("TradeSvr","trade")):
        data=manifest(service)
        path=args.output_dir/(layer+"-e1-recovering.manifest")
        path.write_text(data,encoding="utf-8")
        print("T364_INITIAL_E1_NON_ROUTABLE",
              "service="+service,
              "manifestPath="+args.namespace+layer+"/manifest",
              "homeA=128","homeB=128","ready=0",
              "sha256="+hashlib.sha256(data.encode()).hexdigest(),
              "file="+str(path))
    return 0

if __name__=="__main__":
    sys.exit(main())
