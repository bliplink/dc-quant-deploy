#!/usr/bin/env python3
"""Read-only REAL Demo Robot quote gate. Never creates fake READY or orders.
Reports live Order/Trade service state, legacy cluster route, and the
authoritative Gateway->ManagerSvr robotRuntime heartbeats for a short window.
A positive heartbeat is not yet proof of both sides of MD order book:
the authenticated Robot E2E/real market-depth check remains separately mandatory.
"""
import collections
import re
import json
import pathlib
import subprocess
import sys

SERVICES = ("dc-saas-ordersvr","dc-saas-ordersvr-b","dc-saas-ordersvr-c",
            "dc-saas-tradesvr","dc-saas-tradesvr-b")
STATUS = ("dc-saas-robotsvr","dc-saas-gateway","dc-saas-adminsvr",
          "dc-saas-mdsvr")
def call(*argv):
    r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     universal_newlines=True,timeout=35)
    return r.returncode,r.stdout
def docker_state(container):
    ok,out=call("docker","inspect",container,"--format","{{json .}}")
    if ok:return None
    try:return json.loads(out)
    except ValueError:return None
def physical_properties(info,service):
    target="/srv/dc/dc/"+service+"/config/application.properties"
    paths=[m["Source"] for m in info.get("Mounts",[])
           if m.get("Destination")==target]
    if len(paths)!=1:return None
    f=pathlib.Path(paths[0])
    if not f.is_file() or f.is_symlink():return None
    props={}
    for line in f.read_text(encoding="utf-8",errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith(("#","!")):
            key,val=line.split("=",1)
            if key.strip() not in props:props[key.strip()]=val.strip()
    return props
def heartbeat_lines():
    # Docker may emit logs to stderr; collect one bounded combined stream.
    run=subprocess.run(["docker","logs","--since","100s","--tail","5000","dc-saas-gateway"],
                       stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                       text=True,timeout=35)
    data=run.stdout
    decoder=json.JSONDecoder()
    latest={}
    for line in data.splitlines():
        i=line.find("content:{")
        if i<0:continue
        try:
            blob,_=decoder.raw_decode(line[i+8:])
            if blob.get("method")!="robotRuntime":continue
            body=blob.get("content")
            if not isinstance(body,dict) or body.get("action")!="HEARTBEAT":continue
            location=body.get("location")
            if isinstance(location,str) and 1<=len(location)<=64:
                latest[location]=body
        except (ValueError,TypeError):pass
    return latest
def main():
    if len(sys.argv)>3 or (len(sys.argv)>1 and sys.argv[1]!="--pilot"):
        print("usage: verify-t165-live-demo-robot-quote.py [--pilot TENANT]")
        return 2
    pilot=sys.argv[2] if len(sys.argv)==3 else None
    if len(sys.argv)==2 or (pilot and not re.fullmatch(r"[A-Z0-9]{6}",pilot)):
        print("T165_INVALID_PILOT_TENANT")
        return 2
    blockers=[]
    for container in SERVICES:
        info=docker_state(container)
        if not info or not info["State"]["Running"]:
            blockers.append("SERVICE_DOWN_"+container)
            continue
        name="OrderSvr" if "ordersvr" in container else "TradeSvr"
        prefix="order" if name=="OrderSvr" else "trade"
        props=physical_properties(info,name)
        if not props:
            blockers.append("COMMON_CONFIG_NOT_MOUNTED_"+container)
            continue
        if props.get(prefix+".common.nodeRuntime.phase")!="READY":
            blockers.append("COMMON_NOT_READY_"+container)
        for k in ("lifecycle","failover","replication"):
            if props.get(prefix+".cluster."+k+".enabled")!="false":
                blockers.append("LEGACY_CLUSTER_ENABLED_"+container+"_"+k)
        if props.get(prefix+".common.nodeRuntime.enabled")!="true":
            blockers.append("COMMON_NODE_RUNTIME_DISABLED_"+container)
    for container in STATUS:
        info=docker_state(container)
        if not info or not info["State"]["Running"]:
            blockers.append("DEPENDENCY_DOWN_"+container)
    robot=heartbeat_lines()
    if pilot is not None:
        robot={k:v for k,v in robot.items() if k==pilot}
    tally=collections.Counter(v.get("status","UNKNOWN") for v in robot.values())
    active=[v for v in robot.values() if v.get("status")=="RUNNING"
            and isinstance(v.get("open_order_count"),int)
            and v["open_order_count"]>0]
    failure_sample=next((v.get("error_message","") for v in robot.values()
                         if v.get("status")=="ERROR"),"")
    if not active:blockers.append("NO_REAL_ROBOT_ACTIVE_ORDER_HEARTBEAT")
    if tally.get("ERROR"):blockers.append("ROBOT_RUNTIME_ERRORS_PRESENT")
    # Unlike a synthetic quote callback, the real MD bid/ask must also be
    # checked through the authenticated existing robot E2E host harness.
    print("T165_ROBOT_RUNTIME_WINDOW_SECONDS=100 tenants=%d running_with_orders=%d errors=%d" %
          (len(robot),len(active),tally.get("ERROR",0)))
    if "SERVER.OrderSvr is not Online" in failure_sample:
        print("T165_ROOT_CAUSE=GATEWAY_ORDER_SERVICE_OFFLINE")
    if "SERVER.TradeSvr is not Online" in failure_sample:
        print("T165_ROOT_CAUSE=GATEWAY_TRADE_SERVICE_OFFLINE")
    for item in blockers:print("T165_NO_GO "+item)
    if blockers:
        print("T165_LIVE_ROBOT_BID_ASK_NOT_CERTIFIED; no containers or ZK changed")
        return 3
    print("T165_PRELIMINARY_ROBOT_GW_HEARTBEATS_PASS")
    print("T165_FINAL_GATE_REQUIRES_BID_AND_ASK_MD_DEPTH_AND_REAL_TRADE_E2E")
    return 4
if __name__=="__main__":
    try:sys.exit(main())
    except (OSError,subprocess.SubprocessError) as e:
        print("T165_DIAGNOSTIC_UNAVAILABLE "+type(e).__name__)
        sys.exit(2)