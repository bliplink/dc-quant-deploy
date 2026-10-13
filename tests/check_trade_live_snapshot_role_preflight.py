#!/usr/bin/env python3
"""Fail-closed read-only Trade snapshot role health for active tenant partitions.

Matching Snapshot files do NOT prove WAL ACK, readiness to kill a Primary,
or authority to restart the synchronous Replica. No runtime mutations.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import zlib

try:
    from tests.md_cluster_transition_host import DockerZk
    from tests.verify_trade_rollout_snapshot_headroom import read_metadata, SnapshotEvidenceError
except ModuleNotFoundError:
    from md_cluster_transition_host import DockerZk
    from verify_trade_rollout_snapshot_headroom import read_metadata, SnapshotEvidenceError


def location_partition(location):
    if not isinstance(location,str) or not re.fullmatch(r"[A-Za-z0-9]{1,24}",location):
        raise SnapshotEvidenceError("unsafe tenant location")
    return "P%03d"%(zlib.crc32(location.encode())%256)


def evaluate(assignments, data_root, tenants):
    catalog={r.get("partitionId"):r for r in assignments}
    if len(assignments)!=256 or len(catalog)!=256 or set(catalog)!={"P%03d"%i for i in range(256)}:
        raise SnapshotEvidenceError("incomplete Trade assignment catalog")
    if not data_root.is_dir() or not tenants or len(set(tenants))!=len(tenants):
        raise SnapshotEvidenceError("invalid data root/tenant catalog")
    results=[];partitions=set()
    for tenant in sorted(tenants):
        part=location_partition(tenant)
        if part in partitions:raise SnapshotEvidenceError("multiple active tenants share one Trade partition")
        partitions.add(part)
        assignment=catalog[part]
        epoch=assignment.get("epoch")
        primary=assignment.get("primary")
        replicas=assignment.get("replicas") or [assignment.get("replica")]
        issues=[]
        if not(isinstance(epoch,int) and epoch>0 and assignment.get("state")=="READY"
               and primary in ("TradeSvrA","TradeSvrB") and len(replicas)==1
               and replicas[0] in ("TradeSvrA","TradeSvrB") and replicas[0]!=primary):
            issues.append("INVALID_OR_UNREADY_ASSIGNMENT")
        snaps={}
        if not issues:
            for role,node in (("primary",primary),("replica",replicas[0])):
                path=data_root/node/"snapshot"/part/"latest.json"
                if path.is_symlink() or not path.is_file():
                    issues.append(role.upper()+"_SNAPSHOT_MISSING")
                    continue
                try:
                    meta=read_metadata(path)
                    if meta["partitionId"]!=part or tenant not in meta["locations"]:
                        issues.append(role.upper()+"_SNAPSHOT_IDENTITY_MISMATCH")
                    snaps[role]={"seq":meta["snapshotSeq"],
                                 "stateSeq":meta["committedStateSeq"],
                                 "epoch":meta["epoch"],"bytes":path.stat().st_size}
                except (SnapshotEvidenceError,ValueError,OSError,UnicodeError):
                    issues.append(role.upper()+"_SNAPSHOT_INVALID")
            source,target=snaps.get("primary"),snaps.get("replica")
            if source and (source["epoch"]!=epoch or source["stateSeq"]<=0):
                issues.append("PRIMARY_SNAPSHOT_STALE_EPOCH_OR_EMPTY")
            if target and target["epoch"]!=epoch:
                issues.append("REPLICA_SNAPSHOT_EPOCH_MISMATCH")
            if source and target and source["epoch"]==target["epoch"] and (
                    target["seq"]<source["seq"] or target["stateSeq"]<source["stateSeq"]):
                issues.append("REPLICA_FULL_SNAPSHOT_BEHIND")
        results.append({"tenant":tenant,"partition":part,"currentEpoch":epoch,
                        "primary":primary,"replica":replicas[0] if not issues or replicas else None,
                        "snapshots":snaps,"issues":issues})
    blocked=[{"tenant":x["tenant"],"partition":x["partition"],"issues":x["issues"]}
             for x in results if x["issues"]]
    return {"schema":"trade-live-snapshot-role-preflight-v1",
            "readOnly":True,"checkedAtUtc":datetime.now(timezone.utc).isoformat(),
            "checkedTenants":len(results),"snapshotBlocked":len(blocked),
            "snapshotIssues":blocked,"partitions":results,
            "snapshotPreflight":"BLOCK" if blocked else "UNPROVEN",
            "walCommittedHeadAndAckProof":"NOT_CHECKED",
            "authorizesPrimarySigkill":False,"authorizesReplicaRestart":False,
            "decision":"BLOCKED"}


def tenants_from_audit(path,min_tenants):
    if not path.is_file() or path.is_symlink():raise SnapshotEvidenceError("missing tenant audit")
    audit=json.loads(path.read_text())
    if (audit.get("status")!="PASS_10_TENANT_SNAPSHOT"
            or audit.get("errors") or len(audit.get("tenants") or [])<min_tenants
            or audit.get("observedTenants")!=len(audit.get("tenants") or [])):
        raise SnapshotEvidenceError("tenant audit did not PASS required tenant count")
    stamped=datetime.fromisoformat(audit["timestampUtc"])
    if stamped.tzinfo is None or abs((datetime.now(timezone.utc)-stamped).total_seconds())>900:
        raise SnapshotEvidenceError("tenant audit stale")
    return [row["location"] for row in audit["tenants"]]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root",type=Path,required=True)
    p.add_argument("--tenant-audit",type=Path,required=True)
    p.add_argument("--min-tenants",type=int,default=10)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    try:
        tenants=tenants_from_audit(a.tenant_audit,a.min_tenants)
        zk=DockerZk("dc-saas-zookeeper","127.0.0.1:32181",
                    "/dc/cluster/tradesvr/partitions","docker")
        report=evaluate([x["value"] for x in zk.read_all(256)],a.data_root,tenants)
    except (SnapshotEvidenceError,KeyError,ValueError,OSError,UnicodeError) as error:
        report={"decision":"BLOCKED","readOnly":True,
                "authorizesPrimarySigkill":False,"authorizesReplicaRestart":False,
                "error":str(error)}
    payload=json.dumps(report,indent=2,sort_keys=True)
    if a.output:
        if a.output.exists() or a.output.is_symlink():raise SystemExit("output exists")
        a.output.write_text(payload+"\n")
    print(payload)
    return 2


if __name__=="__main__":
    sys.exit(main())
