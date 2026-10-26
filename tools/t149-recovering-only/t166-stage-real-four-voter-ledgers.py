#!/usr/bin/env python3
"""Stage (but do NOT start) two-real-voter E1 replay proof for T164 four JVMs.
Requires BOTH previously separately signed original RSA birth certs and BOTH
complete same-state immutable E1 restore ledgers, never changes old T149 or
official Demo/ZK or a READY flag. The Java Common JVM re-verifies everything.
"""
import pathlib
import re
import sys

def main():
    if len(sys.argv)!=2:raise SystemExit("usage: t166-stage-real-four-voter-ledgers.py EXACT_T164_ROOT")
    root=pathlib.Path(sys.argv[1])
    if not root.is_absolute() or root.name!="t164-fresh-e1-runtime-20261026":
        raise SystemExit("T166_REFUSE_NONISOLATED_VOLUME")
    if not (root/"compose.yaml").is_file():raise SystemExit("T166_OLD_ISOLATED_COMPOSE_ABSENT")
    names=("ordersvr-a","ordersvr-b","tradesvr-a","tradesvr-b")
    done={}
    for name in names:
        kind="order" if name.startswith("order") else "trade"
        suffix=name[-1]
        other=kind+"svr-"+("b" if suffix=="a" else "a")
        selfroot=root/"data"/name
        peerroot=root/"data"/other
        config=root/"config"/name/"application.properties"
        if not config.is_file() or not peerroot.is_dir():
            raise SystemExit("T166_MISSING_ORIGINAL_MEMBER")
        text=config.read_text(encoding="utf-8")
        if not re.search(r"^"+kind+r"\.common\.nodeRuntime\.installFencedFreshGenesis=true$",text,re.M):
            raise SystemExit("T166_PREVIOUS_SIGNED_E1_INSTALL_NOT_ENABLED "+name)
        original="/otc/t164/"+kind
        if not re.search(r"^"+kind+r"\.common\.nodeRuntime\.freshE1\.namespace="+re.escape(original)+"$",text,re.M):
            raise SystemExit("T166_ORIGINAL_SIGNED_E1_NAMESPACE_CHANGED "+name)
        for physical in (selfroot,peerroot):
            for relative in (
                    "t150-original-genesis/P090/node-voter",
                    "t164-e1-install/P090/ledger/P090.recovery",
                    "t164-e1-install/P090/journal/P090/baseline.properties",
                    "t164-original-wal/P090/original-e1-zero-ack.birth"):
                if not (physical/relative).is_file() and not (physical/relative).is_dir():
                    raise SystemExit("T166_MISSING_ORIGINAL_SIGNED_EVIDENCE "+name+" "+relative)
            if "phase=REPLAY_COMPLETE" not in (
                    physical/"t164-e1-install/P090/ledger/P090.recovery").read_text():
                raise SystemExit("T166_ORIGINAL_REPLAY_INCOMPLETE")
        stem=kind+".common.nodeRuntime.freshE1.P090."
        if stem+"requireBothOriginalReplay=" in text:
            raise SystemExit("T166_ORIGINAL_CONFIG_ALREADY_STAGED "+name)
        own="A" if suffix=="a" else "B"
        rival="B" if own=="A" else "A"
        genesisA=("/srv/dc/data/t150-original-genesis/P090/node-voter"
                  if own=="A" else "/srv/dc/original-e1-other/genesis/P090")
        genesisB=("/srv/dc/data/t150-original-genesis/P090/node-voter"
                  if own=="B" else "/srv/dc/original-e1-other/genesis/P090")
        txnA=("/srv/dc/data/t164-e1-install/P090"
              if own=="A" else "/srv/dc/original-e1-other/install/P090")
        txnB=("/srv/dc/data/t164-e1-install/P090"
              if own=="B" else "/srv/dc/original-e1-other/install/P090")
        additions={
            "requireBothOriginalReplay":"true",
            "primaryOriginalGenesisRoot":genesisA,
            "replicaOriginalGenesisRoot":genesisB,
            "primaryDurableTransactionRoot":txnA,
            "replicaDurableTransactionRoot":txnB,
        }
        done[name]=(config,text,stem,additions,peerroot,kind)
    overlay=["services:"]
    for name,(path,text,stem,add,peer,kind) in done.items():
        srv=name+"164"
        overlay.extend([
            "  "+srv+":",
            "    image: local/otc-t166-"+kind+"svr:both-original-replay",
            "    volumes:",
            '      - "'+str(peer/"t150-original-genesis/P090/node-voter")+':/srv/dc/original-e1-other/genesis/P090:ro"',
            '      - "'+str(peer/"t164-e1-install")+':/srv/dc/original-e1-other/install:ro"',
        ])
    dest=root/"compose.t166-original-rf2-ready-preflight.yaml"
    if dest.exists():raise SystemExit("T166_ALREADY_STAGED")
    for name,(path,text,stem,add,peer,kind) in done.items():
        with path.open("a") as stream:
            for key,val in add.items():stream.write("\n"+stem+key+"="+val)
            stream.write("\n")
    with dest.open("x") as stream:
        stream.write("\n".join(overlay)+"\n")
    print("T166_FOUR_ORIGINAL_RSA_SAME_SESSION_DUAL_REPLAY_SOURCES_STAGED_NO_READY")

if __name__=="__main__":main()