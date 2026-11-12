#!/usr/bin/env python3
"""Restore the retained predecessor of one active Mac Demo generation."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys


FRESH = runpy.run_path(str(Path(__file__).with_name("mac-demo-fresh.py")))
read, run = FRESH["read"], FRESH["run"]


def docker(*command):
    return read("docker", *command)


def inspect(name):
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def restore(root, apply):
    generation = root.name
    candidates = json.loads((root / "retired-containers.json").read_text())
    infra, apps = FRESH["INFRA"], FRESH["APPS"]
    support = FRESH["SUPPORT_IMAGES"]
    expected_fixed = {"dc-saas-"+item for item in (*infra, *apps, *support)}
    if not expected_fixed <= candidates.keys():
        raise RuntimeError("Missing retained Mac Demo infrastructure or support services")
    retained_core = set(candidates)-expected_fixed
    groups = {re.sub(r"-(order|trade)-(a|b)-hostready$", "", name)
              for name in retained_core if re.search(r"-(order|trade)-(a|b)-hostready$", name)}
    if len(groups)!=1:
        raise RuntimeError("Expected one exact retained Order/Trade generation")
    predecessor = groups.pop()
    core = [f"{predecessor}-{svc}-{slot}-hostready" for svc in FRESH["SERVICES"] for slot in ("a", "b")]
    witnesses = [f"{predecessor}-{svc}-witness" for svc in FRESH["SERVICES"]
                 if f"{predecessor}-{svc}-witness" in candidates]
    if (not re.fullmatch(r"mac-demo-\d{8}-\d{6}", predecessor)
            or set(core+witnesses)!=retained_core or predecessor==generation):
        raise RuntimeError("Unexpected retained voter or witness names")
    for name, item in candidates.items():
        if item["retired"]!=f"{generation}-retired-{name}" or not re.fullmatch(r"[0-9a-f]{64}", item["id"]):
            raise RuntimeError("Unexpected saved rollback container identity")
        actual=inspect(item["id"])
        if not actual or actual["Name"]!="/"+item["retired"] or actual["State"]["Running"]:
            raise RuntimeError("The original retained container is missing, renamed, or already running: "+name)
        if name in expected_fixed and actual["Config"]["Labels"].get("com.docker.compose.project")!=predecessor:
            raise RuntimeError("A retained support container belongs to a different project: "+name)
        if name in expected_fixed:
            active=inspect(name)
            if not active or active["Config"]["Labels"].get("com.docker.compose.project")!=generation:
                raise RuntimeError("The reviewed Mac Demo is no longer active for "+name)
            if inspect(f"{generation}-held-{name}"):
                raise RuntimeError("A preserved container name is already occupied: "+name)
        elif inspect(name):
            raise RuntimeError("A retained voter name is already occupied: "+name)
    print(f"[mac-demo] Restore {predecessor}; preserve all data from {generation}", flush=True)
    if not apply:
        return
    active = {name: inspect(name)["Id"] for name in expected_fixed}
    core_running = docker("ps", "-q", "--filter", f"label=otc.mac.demo.generation={generation}").splitlines()
    fixed_running = [active[name] for name in expected_fixed if inspect(active[name])["State"]["Running"]]
    front = [identifier for identifier in fixed_running
             if inspect(identifier)["Name"].lstrip("/") not in {"dc-saas-"+x for x in infra}]
    back = sorted(set(fixed_running)-set(front))
    for group in (front+core_running, back):
        if group:
            docker("stop", "--time", "45", *group)
    for name, identifier in sorted(active.items()):
        docker("rename", identifier, f"{generation}-held-{name}")
    for name,item in candidates.items():
        docker("rename", item["id"], name)
    for group in (["dc-saas-"+x for x in infra], ["dc-saas-"+x for x in apps],
                  witnesses, core, ["dc-saas-"+x for x in support]):
        running=[name for name in group if candidates[name]["running"]]
        if running:
            docker("start", *running)
            print("[mac-demo] Started "+", ".join(running), flush=True)
    result=root/"restored-predecessor.json"
    temporary=result.with_suffix(".tmp")
    temporary.write_text(json.dumps({"active":predecessor,"held":generation,"held_services":active},sort_keys=True)+"\n")
    temporary.replace(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation",type=Path)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    root=args.generation.resolve(strict=True)
    if (root.parent!=FRESH["LOCAL"].resolve() or not re.fullmatch(r"mac-demo-\d{8}-\d{6}",root.name)
            or read("uname","-s")!="Darwin" or docker("context","show")!="colima"):
        raise RuntimeError("Expected an original Mac Colima Demo generation")
    os.umask(0o077)
    with (root.parent/".mac-demo-fresh.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        restore(root,args.apply)


if __name__=="__main__":
    try:
        main()
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
        sys.exit(str(exc) if isinstance(exc,(RuntimeError,OSError)) else "Docker command failed during retained restoration")
