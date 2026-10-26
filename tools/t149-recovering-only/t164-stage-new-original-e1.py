#!/usr/bin/env python3
"""T164 fresh never-serving E1 configs, NO READY, ZK or Docker mutation.
Copies config only into an isolated, pre-provisioned original-RSA birth root.
Do not use this staging tool for T149, official Demo, or historical WAL.
"""
import os
import pathlib
import re
import sys

def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: t164-stage-config.py EXACT_OLD_T149_ROOT EXACT_NEW_T164_ROOT")
    old=pathlib.Path(sys.argv[1])
    root=pathlib.Path(sys.argv[2])
    if not old.is_absolute() or not root.is_absolute() or (
        old.name != "t149-order-trade-deploy-20261026"
        or root.name != "t164-fresh-e1-runtime-20261026"):
        raise SystemExit("T164_DENIED_WRONG_ISOLATED_RUNTIME_ROOTS")
    if not (old/"compose.yaml").is_file() or not (root/"data").is_dir():
        raise SystemExit("T164_MISSING_ORIGINAL_OR_FRESH_INPUT")
    env=(old/".env").read_text()
    matches=re.findall(r"^EXISTING_RSA_ROOT=(.+)$",env,re.MULTILINE)
    if len(matches)!=1:
        raise SystemExit("T164_ORIGINAL_RSA_ENV_MISSING")
    rsa=pathlib.Path(matches[0].strip().strip('"').strip("'"))
    if not rsa.is_absolute() or not (rsa/"public"/"CommonHaDemoA.pub.der").is_file():
        raise SystemExit("T164_PINNED_OLD_RSA_NOT_MOUNTED")
    specs=[
        ("ordersvr-a164","ordersvr-a","order","OrderSvr","OrderSvrA","a","ordersvr"),
        ("ordersvr-b164","ordersvr-b","order","OrderSvr","OrderSvrB","b","ordersvr"),
        ("tradesvr-a164","tradesvr-a","trade","TradeSvr","TradeSvrA","a","tradesvr"),
        ("tradesvr-b164","tradesvr-b","trade","TradeSvr","TradeSvrB","b","tradesvr"),
    ]
    for service,src,kind,name,node,slot,image in specs:
        physical=root/"data"/src
        original=physical/"t150-original-genesis"/"P090"
        fresh=physical/"t164-original-wal"/"P090"
        if not (original/"sealed"/"genesis-e1.quorum").is_file():
            raise SystemExit("T164_SIGNED_GENESIS_NOT_PRESERVED "+src)
        if not (fresh/"original-e1-zero-ack.birth").is_file():
            raise SystemExit("T164_BIRTH_TIME_RSA_MISSING "+src)
        if not (physical/"t164-e1-install"/"P090").is_dir():
            raise SystemExit("T164_INITIAL_TRANSACTION_ROOT_NOT_PREPARED "+src)
        destination=root/"config"/src/"application.properties"
        if destination.exists():
            raise SystemExit("T164_CONFIG_ALREADY_EXISTS_REFUSE_REWRITE "+src)
    compose=["name: otc-t164-new-original-e1","services:"]
    for service,src,kind,name,node,slot,image in specs:
        first=name+"A";second=name+"B"
        t14=(old/"config"/src/"application.properties").read_text()
        original_namespace="/otc/t149/"+kind
        new_namespace="/otc/t164/"+kind
        if t14.count(original_namespace)<2:
            raise SystemExit("T164_ORIGINAL_MANIFEST_NAMESPACE_NOT_PINNED "+src)
        t14=t14.replace(original_namespace,new_namespace)
        if kind+".common.nodeRuntime.installFencedFreshGenesis=" in t14:
            raise SystemExit("T164_OLD_CONFIG_CONTAINS_INSTALL_OVERRIDE")
        keys=[
            (kind+".common.nodeRuntime.inspectFencedBusiness","true"),
            (kind+".common.nodeRuntime.installFencedFreshGenesis","false"),
        ]
        prefix=kind+".common.nodeRuntime.freshE1."
        keys.append((prefix+"namespace",new_namespace))
        stem=prefix+"P090."
        for attr,value in [
            ("primary",first),("replica",second),
            ("primaryRsaAlias","CommonHaDemoA"),("replicaRsaAlias","CommonHaDemoB"),
            ("primaryPhysicalHost","t150-isolated-volume-"+first),
            ("replicaPhysicalHost","t150-isolated-volume-"+second),
            ("originalSignedQuorum","/srv/dc/data/t150-original-genesis/P090/sealed"),
            ("localDurableGenesis","/srv/dc/data/t150-original-genesis/P090/node-voter"),
            ("durableTransactionRoot","/srv/dc/data/t164-e1-install/P090"),
            ("primaryOriginalWalRoot","/srv/dc/birth-voters/P090/A"),
            ("replicaOriginalWalRoot","/srv/dc/birth-voters/P090/B")]:
            keys.append((stem+attr,value))
        for key,value in keys:
            if any(x.startswith(key+"=") for x in t14.splitlines()):
                raise SystemExit("T164_DUPLICATE_FRESH_E1_CONFIG "+key)
            t14+="\n"+key+"="+value
        t14+="\n"
        config=root/"config"/src/"application.properties"
        config.parent.mkdir(parents=True,exist_ok=True)
        with config.open("x") as w:w.write(t14)
        os.chmod(config,0o600)
        physical=root/"data"/src
        peerA=root/"data"/(kind+"svr-a")/"t164-original-wal"/"P090"
        peerB=root/"data"/(kind+"svr-b")/"t164-original-wal"/"P090"
        target="/srv/dc/dc/"+name+"/config/application.properties"
        compose.extend([
            "  "+service+":",
            "    image: local/otc-t163-"+image+":original-e1-install-hook",
            "    restart: \"no\"",
            "    networks: [old-zk-isolated]",
            "    mem_limit: 800m",
            "    cpus: 0.7",
            '    environment:',
            '      JAVA_OPTS: "-server -Xms64m -Xmx384m -Xmn96m -XX:+UseSerialGC -Ddc.zookeeper.sessionTimeoutMs=8000"',
            "    volumes:",
            "      - "+str(config)+":"+target+":ro",
            "      - "+str(rsa/slot)+":/read-only-original-rsa/"+slot+":ro",
            "      - "+str(rsa/"public")+":/read-only-original-rsa/public:ro",
            "      - "+str(physical)+":/srv/dc/data",
            "      - "+str(root/"logs"/src)+":/srv/dc/log",
            "      - "+str(peerA)+":/srv/dc/birth-voters/P090/A:ro",
            "      - "+str(peerB)+":/srv/dc/birth-voters/P090/B:ro",
        ])
    compose+=["networks:","  old-zk-isolated:","    external: true",
              "    name: otc-t149-ha-intake_test-isolated"]
    with (root/"compose.yaml").open("x") as out:out.write("\n".join(compose)+"\n")
    print("T164_FOUR_ORIGINAL_RSA_GENUINE_E1_RECOVERING_CONFIGS_STAGED_NO_READY_NO_DEPLOY_PASS")

if __name__=="__main__":main()