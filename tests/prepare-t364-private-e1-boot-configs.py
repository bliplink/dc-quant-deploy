#!/usr/bin/env python3
"""Prepare independent T364 Common E1 birth/replay configs from audited T318
template semantics. Does NOT copy old birth/signatures, mutate ZK or READY,
start business, or print credentials.
"""
from pathlib import Path
import argparse, os, re, secrets, sys

OLD_NS="t318-virgin-20261029-r1"
NEW_NS="t364-fresh-20261031-r1"
REPLACE=((OLD_NS,NEW_NS),("t318-born","t364-born"),
         ("common-t318-data","common-t364-data"))

def prepare(previous: Path,new: Path):
    if not previous.is_dir() or previous.is_symlink():
        raise ValueError("T364 original verified configuration unavailable")
    for service in ("order","trade"):
        for alias in ("A","B"):
            if not (previous/service/alias/"application.properties").is_file():
                raise ValueError("T364 original per-physical-node template missing")
    if (new/"config").exists() or (new/"born").exists() or (new/"data").exists():
        raise ValueError("T364 signed birth/config root is not virgin")
    (new/"config").mkdir(parents=True,mode=0o700)
    (new/"born").mkdir(mode=0o700)
    (new/"data").mkdir(mode=0o700)
    for service in ("order","trade"):
        for alias in ("A","B"):
            src=previous/service/alias
            dst=new/"config"/service/alias
            dst.mkdir(parents=True,mode=0o700)
            token=secrets.token_hex(24)
            for name in ("application.properties","hold.properties",
                         "install.properties",
                         *(( "signed-first-ready.properties",) if alias=="A" else ())):
                text=(src/name).read_text(encoding="utf-8")
                for old,replacement in REPLACE:
                    text=text.replace(old,replacement)
                if OLD_NS in text or "t318-born" in text:
                    raise ValueError("T364 stale signed namespace in configuration")
                key=service+".common.control.ownerToken"
                pattern=re.compile(r"(?m)^"+re.escape(key)+r"=.*$")
                text,count=pattern.subn(lambda _:key+"="+token,text)
                if count!=1:
                    raise ValueError("T364 lease identity not configured exactly once")
                root=new/"config"/service/alias/name
                root.write_text(text,encoding="utf-8")
                os.chmod(root,0o600)
            print("T364_NEW_PRIVATE_CONFIG_PREPARED",
                  "service="+service,"physicalNode="+alias,
                  "newNamespace=/otc/"+NEW_NS+"/"+service,
                  "oldSignerKeysRetained=true","bornFiles=0","READY=false")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--previous-run",required=True,type=Path)
    parser.add_argument("--new-run",required=True,type=Path)
    args=parser.parse_args()
    try:
        prepare(args.previous_run,args.new_run)
        return 0
    except (ValueError,OSError) as exc:
        print("T364_BOOT_CONFIG_FAIL_CLOSED "+str(exc),file=sys.stderr)
        return 4

if __name__=="__main__":
    sys.exit(main())
