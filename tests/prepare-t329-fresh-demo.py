#!/usr/bin/env python3
"""T329 reusable fresh Demo profiles from *original* T318 RSA-signed E2 Genesis.
No reuse of old T325 business WAL and no editing of original RSA or ZK data.
"""
from pathlib import Path
import os,re,sys
ROOT=Path.home()/".opentradingcore"
BIRTH=ROOT/"t318-virgin-20261029"/"born"
BASE=ROOT/"t319-business-ready-20261030"
OUTPUT=ROOT/"t329-fresh-demo-20261030"/"config"
NAMESPACE="/otc/t318-virgin-20261029-r1"
HOSTS="192.168.128.7:2181,192.168.128.8:2181,192.168.128.9:2181"
REPLACE_ZK="otc-t84-source-integrated-otc-ha-zk1-1:2181,otc-t84-source-integrated-otc-ha-zk2-1:2181,otc-t84-source-integrated-otc-ha-zk3-1:2181"
CONF={"order":("OrderSvr",{"A":(45322,33036),"B":(45323,33041)}),
      "trade":("TradeSvr",{"A":(45222,33037),"B":(45223,33046)})}
def modify(raw,key,val):
    pat=r"(?m)^"+re.escape(key)+r"=.*$"
    raw,n=re.subn(pat,lambda _:key+"="+val,raw)
    if n!=1: raise ValueError("missing/duplicate "+key)
    return raw
def main():
    for kind,(service,nodes) in CONF.items():
        signed=BIRTH/service/"sealed"
        if sum((signed/("P%03d"%i)/"genesis-e1.quorum").is_file() for i in range(256))!=256:
            raise ValueError("unsigned original "+service+" Genesis")
        if not (BIRTH/service/"first-ready/e1-to-e2-A.signed").is_file():
            raise ValueError("missing original signed First-Ready "+service)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for kind,(service,nodes) in CONF.items():
        for n,(port,gw) in nodes.items():
            original=(BASE/kind/n/"application.v4.properties").read_text()
            if REPLACE_ZK not in original:raise ValueError("unsupported original ZK")
            raw=original.replace(REPLACE_ZK,HOSTS)
            raw=raw.replace("otc-t319-"+kind+"-a:","127.0.0.1:").replace("otc-t319-"+kind+"-b:","127.0.0.1:")
            raw=modify(raw,kind+".common.nodeRuntime.dataRoot","/srv/dc/data/t329-fresh/"+
                    service+"/"+service+n)
            raw=modify(raw,kind+".common.gatewayDiscovery.enabled","true")
            raw=modify(raw,kind+".common.gatewayDiscovery.port",str(gw))
            raw=modify(raw,kind+".common.control.ownerToken","T329-DEMO-FRESH-"+service+n)
            if (REPLACE_ZK in raw or "t319-ready-v4" in raw
                or "t325-trading-e2" in raw or "otc-t319-" in raw):
                raise ValueError("contains old/t319 bridge runtime "+service+n)
            if NAMESPACE+"/"+kind+"/manifest" not in raw or "t318-born" not in raw:
                raise ValueError("wrong signed E2 namespace/birth")
            dest=OUTPUT/(service+n+".properties")
            dest.write_text(raw if raw.endswith("\n") else raw+"\n")
            dest.chmod(0o600)
            d=ROOT/"dc-saas-runtime-clean-20261016"/"data"/"t329-fresh"/service/(service+n)
            if d.exists() and any(d.iterdir()):
                raise ValueError("nonempty T329 WAL exists; never recreate genesis: "+str(d))
            d.mkdir(parents=True,exist_ok=True)
            print("T329_FRESH_COMMON_SIGNED_CONFIG_READY service="+service+n+
                  " port="+str(port)+" gateway="+str(gw)+
                  " signedGenesis=256 newEmptyWAL=true")
    print("T329_PREPARE_PASS t318OriginalBirth=readOnly newBusinessWal=empty oldSignedWAL=unchanged")
if __name__=="__main__":
    try:main()
    except Exception as ex:
        print("T329_PREPARE_NO_GO: "+str(ex),file=sys.stderr);sys.exit(2)
