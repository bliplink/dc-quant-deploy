#!/usr/bin/env python3
"""Prepare the existing T319 Order/Trade binaries for T181 formal Demo signed E2.
Does not mutate original T181 RSA/Genesis/WAL or production services.
"""
from pathlib import Path
import os, re, sys

HERE=Path(__file__).resolve().parent.parent
BASE=Path.home()/".opentradingcore"
FORMAL=BASE/"dc-saas-runtime-clean-20261016"
T319=BASE/"t319-business-ready-20261030"
OUTPUT=BASE/"t325-trading-restore-20261030"/"config"
SERVICES={"order":"OrderSvr","trade":"TradeSvr"}
BRIDGE="otc-t84-source-integrated-"
NAMESPACE="/otc/demo-t181-fresh-20261027"
PREFS={
 "order":{"A":(45322,33036),"B":(45323,33041)},
 "trade":{"A":(45222,33037),"B":(45223,33046)},
}
def update(src:Path,dest:Path, mapping:dict[str,str], extra:dict[str,str]):
    raw=src.read_text()
    original=raw
    for before,after in mapping.items():
        if before not in raw:raise ValueError(f"{src}: required source token missing: {before}")
        raw=raw.replace(before,after)
    for key,value in extra.items():
        pattern=r"(?m)^"+re.escape(key)+r"=.*$"
        line=key+"="+value
        if re.search(pattern,raw):
            raw,n=re.subn(pattern,lambda match:line,raw)
            if n!=1: raise ValueError(f"{src}: duplicate {key}")
        else: raw+="\n"+line+"\n"
    if BRIDGE in raw or "t318-born" in raw or "t319-ready-v4" in raw:
        raise ValueError(f"{src}: still references isolated roots")
    if not raw.endswith("\n"):raw+="\n"
    dest.write_text(raw)
    dest.chmod(0o600)
    return len(raw)
def main():
    for service,svc in SERVICES.items():
        birth=FORMAL/"data"/"common-t181-born"/svc
        for key in ("A","B"):
            if not (birth/(svc+key)).is_dir():
                raise SystemExit(f"missing original dual-E1 birth {birth}/{svc+key}")
        sealed=birth/"sealed"
        n=sum((sealed/f"P{i:03d}"/"genesis-e1.quorum").is_file() for i in range(256))
        if n!=256:raise SystemExit(f"{svc} valid sealed Genesis file count {n}/256")
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for service,svc in SERVICES.items():
        for node,(port,gwport) in PREFS[service].items():
            src=T319/service/node/"application.v4.properties"
            dest=OUTPUT/f"{svc}{node}.properties"
            ns=f"{NAMESPACE}/{service}"
            mapping={
                f"/otc/t318-virgin-20261029-r1/{service}":ns,
                "/srv/dc/data/t318-born":"/srv/dc/data/common-t181-born",
                "/srv/dc/data/t319-ready-v4":"/srv/dc/data/t325-trading-e2",
                f"{BRIDGE}otc-ha-zk1-1:2181,{BRIDGE}otc-ha-zk2-1:2181,{BRIDGE}otc-ha-zk3-1:2181":"127.0.0.1:32181",
                f"{svc}A@otc-t319-{service}-a:{PREFS[service]['A'][0]},{svc}B@otc-t319-{service}-b:{PREFS[service]['B'][0]}":
                  f"{svc}A@127.0.0.1:{PREFS[service]['A'][0]},{svc}B@127.0.0.1:{PREFS[service]['B'][0]}",
            }
            extra={
              f"{service}.common.gatewayDiscovery.enabled":"true",
              f"{service}.common.gatewayDiscovery.host":"127.0.0.1",
              f"{service}.common.gatewayDiscovery.port":str(gwport)
            }
            size=update(src,dest,mapping,extra)
            print(f"T325_CONFIG_READY {svc}{node} bytes={size} zk=formal:32181 genesis=T181-signed-E2 gwport={gwport}")
    print("T325_PREPARE_CONFIG_PASS existingRSA=unchanged existingWAL=unchanged")
if __name__=="__main__":main()
