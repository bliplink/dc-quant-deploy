#!/usr/bin/env python3
"""T460: only real 3-ZK signed poison Stage, NEVER customer READY/real WAL.

Two independent Docker JVMs, independent A/B RSA keys and live ephemeral
sessions. 256 assignments; only P060 may become non-routable RECOVERING.
All test containers and ZooKeeper volumes are removed, evidence retained.
"""
import argparse
import hashlib
import pathlib
import runpy
import secrets
import subprocess
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parents[1]
LEGACY=runpy.run_path(str(ROOT/"tests/run-t376-isolated-common-zk-stage.py"))
ZK_IMAGE=LEGACY["ZK_IMAGE"]
DEMO_IMAGE=LEGACY["DEMO_IMAGE"]
COMPOSE_TEXT=LEGACY["compose_text"]

def invoke(args,timeout=40):
    return subprocess.run([str(x) for x in args],capture_output=True,
                          text=True,timeout=timeout)

def check(proc,where):
    if proc.returncode:
        raise RuntimeError(
            where+" exit="+str(proc.returncode)+"\n"+
            proc.stdout[-1400:]+"\n"+proc.stderr[-1100:])
    return proc

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=pathlib.Path,required=True)
    parser.add_argument("--expected-sha256",required=True)
    parser.add_argument("--classes",type=pathlib.Path,required=True)
    parser.add_argument("--keys",type=pathlib.Path,required=True)
    parser.add_argument("--pin-original-home",action="store_true",
                        help="T462: force 256 pinned Home while B takes over A's poisoned P060")
    args=parser.parse_args()
    candidate=args.candidate.resolve(strict=True)
    classes=args.classes.resolve(strict=True)
    keys=args.keys.resolve(strict=True)
    if hashlib.sha256(candidate.read_bytes()).hexdigest()!=args.expected_sha256:
        raise RuntimeError("T460 Common candidate byte SHA differs from pinned source")
    cname="com/app/common/replication/CommonT460PoisonedPrimaryRealZkProcess.class"
    if not (classes/cname).is_file():
        raise RuntimeError("T460 test-only process class missing")
    for file in ("a/node.pk8","b/node.pk8",
                 "public/CommonHaDemoA.pub.der","public/CommonHaDemoB.pub.der"):
        if not (keys/file).is_file():
            raise RuntimeError("T460 isolated TEST RSA identity missing "+file)
    for image in (ZK_IMAGE,DEMO_IMAGE):
        check(invoke(["docker","image","inspect",image],timeout=20),
              "T460 preinstalled test image")
    suffix=secrets.token_hex(4)
    project="otc-t460-"+suffix
    network=project+"-net"
    oldname=project+"-old-a"
    zkroot="/dc/cluster/t460-"+suffix
    evidence=ROOT/".work/t460-live-poison-evidence"/suffix
    evidence.mkdir(parents=True,exist_ok=False)
    (evidence/"b-ledger").mkdir()
    yaml=evidence/(project+".yaml")
    yaml.write_text(COMPOSE_TEXT(network))
    call=["docker","compose","-p",project,"-f",yaml]
    cp="/t460/probe:/t460/common.jar:/srv/dc/dc/GW/lib/*"
    common=["--network",network,
            "-v",str(candidate)+":/t460/common.jar:ro",
            "-v",str(classes)+":/t460/probe:ro",
            "-v",str(keys/"public")+":/rsa/public:ro",
            "-e","OTC_T460_ZK_ROOT="+zkroot]
    if args.pin_original_home:
        common += ["-e","OTC_T462_PIN_HOME=1"]
    java="com.app.common.replication.CommonT460PoisonedPrimaryRealZkProcess"
    def command(action,side=None,name=None,extras=None):
        cmd=["docker","run"]
        if name:cmd+=["-d","--name",name]
        else:cmd+=["--rm"]
        cmd+=common
        if side:cmd+=["-v",str(keys/side/"node.pk8")+":/rsa/"+side+"/node.pk8:ro"]
        if extras:cmd+=extras
        return cmd+["--entrypoint","java",DEMO_IMAGE,"-cp",cp,java,action]
    started=False
    try:
        check(invoke(call+["up","-d","--pull","never"],timeout=110),
              "T460 independent three-ZK start")
        started=True
        ready=False
        for _ in range(40):
            ps=invoke(call+["ps","-q"],timeout=20)
            nodes=[x for x in ps.stdout.splitlines() if x.strip()]
            if len(nodes)==3:
                health=invoke(["docker","exec",nodes[0],"bash","-c",
                               "echo ruok | nc -w 2 127.0.0.1 2181"],timeout=15)
                if "imok" in health.stdout:
                    ready=True
                    break
            time.sleep(1)
        if not ready:raise RuntimeError("T460 real three-ZK quorum unavailable")
        bootstrap=check(invoke(command("--bootstrap"),timeout=50),
                        "T460 actual ZK 256 READY bootstrap")
        (evidence/"bootstrap.log").write_text(bootstrap.stdout+bootstrap.stderr)
        if "T460_REAL_3ZK_256_ORIGINAL_READY_BOOTSTRAPPED_PASS" not in bootstrap.stdout:
            raise RuntimeError("T460 bootstrap missing actual NPC1 census")
        owner=check(invoke(command("--poisoned-A","a",name=oldname),timeout=25),
                    "T460 original A independent JVM")
        alive=False
        for _ in range(90):
            state=invoke(["docker","inspect",oldname,
                          "--format","{{.State.Running}}"],timeout=10)
            logs=invoke(["docker","logs",oldname],timeout=10)
            if "T460_OLD_A_LIVE_RSA_SIGNED_POISON_EPHEMERAL_PASS" in logs.stdout:
                alive=True
                break
            if state.stdout.strip()!="true":
                raise RuntimeError("T460 original A terminated without RSA poison\n"+
                                   logs.stdout[-1000:]+logs.stderr[-1000:])
            time.sleep(.35)
        if not alive:raise RuntimeError("T460 original A did not persist signed ZK marker")
        (evidence/"old-a.log").write_text(logs.stdout+logs.stderr)
        b=check(invoke(command("--candidate-B","b",extras=[
                "-v",str(evidence/"b-ledger")+":/srv/t460-signed-stage:rw"]),
                timeout=85),"T460 live old-owner signed watch")
        (evidence/"candidate-b.log").write_text(b.stdout+b.stderr)
        if "T460_REAL_3ZK_LIVE_POISON_SIGNED_AUTO_WATCH_STAGE_PASS" not in b.stdout:
            raise RuntimeError("T460 missed signed live-poison A→B nonREADY Stage")
        if args.pin_original_home and (
                "T462_REAL_3ZK_256_PINNED_HOME_NONHOME_B_POISON_STAGE_PASS"
                not in b.stdout):
            raise RuntimeError("T462 pinned original Home incorrectly blocked non-Home B")
        still=invoke(["docker","inspect",oldname,
                      "--format","{{.State.Running}}"],timeout=10)
        if still.stdout.strip()!="true":
            raise RuntimeError("T460 falsely claimed A kept serving 255 shards")
        print("T460_PINNED_COMMON_SHA256="+args.expected_sha256)
        print("T460_EVIDENCE_DIR="+str(evidence))
        for line in (bootstrap.stdout+logs.stdout+b.stdout).splitlines():
            if line.startswith("T460_"):print(line)
        return 0
    finally:
        oldlogs=invoke(["docker","logs",oldname],timeout=12)
        if oldlogs.returncode==0:
            (evidence/"old-a-final.log").write_text(oldlogs.stdout+oldlogs.stderr)
        invoke(["docker","rm","-f",oldname],timeout=20)
        if started:
            result=invoke(call+["down","--volumes","--remove-orphans"],timeout=80)
            print("T460_ISOLATED_3ZK_CLEANUP="+str(result.returncode==0),flush=True)

if __name__=="__main__":
    sys.exit(main())