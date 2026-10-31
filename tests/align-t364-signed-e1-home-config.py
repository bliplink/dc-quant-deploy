#!/usr/bin/env python3
"""Align private *uncommitted* T364 E1 replay configuration with signed original
A Home P000-P127, B Home P128-P255. Does not touch original RSA, ZK or born.
"""
import argparse
from pathlib import Path
import re
import sys

FIELDS={
    "primary", "replica", "primaryRsaAlias", "replicaRsaAlias",
    "primaryPhysicalHost", "replicaPhysicalHost",
    "primaryOriginalWalRoot", "replicaOriginalWalRoot"
}
PARTITION=re.compile(r"^(order|trade)\.common\.nodeRuntime\.freshE1\.P(\d{3})\.([A-Za-z0-9]+)=(.*)$")

def validate_blank_transactions(data:Path):
    for root in data.glob("*/*/tx/P???"):
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise ValueError("T364 E1 replay transaction already modified; config update denied")

def patch(root:Path):
    if root.name!="t364-fresh-20261031-r1":
        raise ValueError("exact independent virgin namespace required")
    validate_blank_transactions(root/"data")
    changed=0
    for svc,name in (("order","OrderSvr"),("trade","TradeSvr")):
        for node in ("A","B"):
            base=root/"config"/svc/node
            filenames=("install.properties","signed-first-ready.properties") if node=="A" else ("install.properties",)
            for filename in filenames:
                file=base/filename
                text=file.read_text(encoding="utf-8")
                original=text.splitlines(keepends=True)
                updated=[];seen=set()
                for line in original:
                    match=PARTITION.match(line.rstrip("\n"))
                    if not match or match.group(1)!=svc or match.group(3) not in FIELDS:
                        updated.append(line);continue
                    n=int(match.group(2))
                    if not (0<=n<256):raise ValueError("invalid bounded partition index")
                    home="A" if n<128 else "B";peer="B" if n<128 else "A"
                    field=match.group(3)
                    values={
                        "primary":name+home,
                        "replica":name+peer,
                        "primaryRsaAlias":"CommonHaDemo"+home,
                        "replicaRsaAlias":"CommonHaDemo"+peer,
                        "primaryPhysicalHost":"MacDockerSlot"+home,
                        "replicaPhysicalHost":"MacDockerSlot"+peer,
                        "primaryOriginalWalRoot":f"/srv/dc/data/t364-born/{name}/{name+home}/original-wal/P{n:03d}",
                        "replicaOriginalWalRoot":f"/srv/dc/data/t364-born/{name}/{name+peer}/original-wal/P{n:03d}",
                    }
                    key=(n,field)
                    if key in seen:raise ValueError("duplicate original E1 property")
                    seen.add(key)
                    updated.append(f"{match.group(1)}.common.nodeRuntime.freshE1.P{n:03d}.{field}={values[field]}\n")
                    changed+=line!=updated[-1]
                if len(seen)!=256*len(FIELDS):
                    raise ValueError("T364 incomplete signed Membership config")
                file.write_text("".join(updated),encoding="utf-8")
                file.chmod(0o600)
                print("T364_SIGNED_E1_PLAN_CONFIG_MATCH",
                      svc,node,filename,"AHome=128","BHome=128","fields=2048")
    return changed

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True)
    args=p.parse_args()
    try:
        print("T364_ONLY_PRIVATE_CONFIG_FIELDS_UPDATED",patch(args.root))
    except (OSError,ValueError) as error:
        print("T364_E1_LAYOUT_CONFIG_DENIED",error,file=sys.stderr);sys.exit(4)
