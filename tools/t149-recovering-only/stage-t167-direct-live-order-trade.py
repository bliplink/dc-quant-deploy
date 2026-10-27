#!/usr/bin/env python3
"""T167: prepare real dc-saas Order/Trade Common-only startup configuration.
This deliberately targets LIVE dc-saas Compose, not T149/T164 isolation.
No bypass/READY grant: certified Common Spring wiring must reject missing
physical state, ZK authority and recovered domain; never restart legacy HA.
Original configs remain untouched for rollback. Demo can be reset later only
after a real signed fresh Genesis and physical custody are in place.
"""
import pathlib,re,sys,json,os
def main():
    if len(sys.argv)!=2:raise SystemExit("usage: stage-t167-direct-live-order-trade.py /Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016")
    root=pathlib.Path(sys.argv[1]).resolve()
    if str(root)!="/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016":
        raise SystemExit("REFUSE_UNVERIFIED_DEMO_ROOT")
    originals=root/"control"/"overrides"
    target=root/"control"/"common-t167-direct-live"
    if target.exists():raise SystemExit("DIRECT_LIVE_T167_ALREADY_STAGED")
    names=(("ordersvr","OrderSvrA","order","OrderSvr","local/otc-t167-ordersvr:demo-common-only"),
           ("tradesvr","TradeSvrA","trade","TradeSvr","local/otc-t167-tradesvr:demo-common-only"))
    sources={}
    for svc,node,prefix,business,image in names:
        source=originals/node/"config"/"application.properties"
        if not source.is_file() or source.is_symlink():
            raise SystemExit("MISSING_OFFICIAL_CONFIG_"+node)
        original=source.read_text()
        if not re.search(r"^"+prefix+r"\.cluster\.lifecycle\.enabled=true$",original,re.M):
            raise SystemExit("NOT_ORIGINAL_T113_LEGACY_CONFIG")
        sources[node]=(source,original,prefix,business,image,svc)
    target.mkdir(mode=0o700)
    overlay=["services:"]
    for node,(source,original,prefix,business,image,svc) in sources.items():
        modified=original
        for suffix in ("lifecycle","failover","replication"):
            key=prefix+".cluster."+suffix+".enabled"
            modified,count=re.subn(r"^"+re.escape(key)+r"=true$",key+"=false",modified,flags=re.M)
            if count!=1:raise SystemExit("INVALID_ORIGINAL_LEGACY_FLAG_"+key)
        # Explicit Common-only entry. These booleans are prerequisites, NOT
        # authorization or a fake external Common certificate.
        additions={
            prefix+".common.cluster.required":"true",
            prefix+".common.control.enabled":"true",
            prefix+".common.physicalEvidence.enabled":"true",
            prefix+".common.nodeRuntime.enabled":"true",
            prefix+".common.nodeRuntime.phase":"READY",
            prefix+".common.nodeRuntime.service":business,
            prefix+".common.nodeRuntime.dataRoot":"/srv/dc/data/common-t167-direct/"+business+"/"+node,
            prefix+".common.control.zkHosts":"127.0.0.1:32181",
            prefix+".common.control.nodeId":node.replace("A","A"),
            prefix+".common.control.manifestPath":"/otc/demo-real-common/order/manifest" if prefix=="order" else "/otc/demo-real-common/trade/manifest",
            prefix+".common.control.leasePath":"/otc/demo-real-common/"+prefix+"/leases/"+node,
            prefix+".common.durableHandoff.enabled":"true",
        }
        for key,value in additions.items():
            if re.search(r"^"+re.escape(key)+r"=",modified,re.M):
                raise SystemExit("MUST_NOT_OVERRIDE_EXISTING_COMMON_PROPERTY_"+key)
            modified+="\n"+key+"="+value
        cfg=target/(node+".properties")
        with cfg.open("x") as stream:stream.write(modified+"\n")
        os.chmod(cfg,0o600)
        overlay += [
            "  "+svc+":",
            "    image: "+image,
            '    restart: "no"',
            "    volumes:",
            '      - "'+str(cfg)+':/srv/dc/dc/'+business+'/config/application.properties:ro"',
        ]
    out=target/"compose.t167-live.yaml"
    with out.open("x") as stream:stream.write("\n".join(overlay)+"\n")
    print("T167_LIVE_ORDER_TRADE_PRIMARY_CONFIG_STAGED no-old-HA, Common-READY-REQUIRES-REAL-PROOF; ORIGINALS_UNCHANGED")
    print("COMPOSE_OVERRIDE="+str(out))
if __name__=="__main__":main()