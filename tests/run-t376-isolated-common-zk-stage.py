#!/usr/bin/env python3
"""T376 real ZooKeeper E1 -> E2 RECOVERING stage with isolated Docker network.

This is deliberately NOT full HA READY: automatic survivor watches stage a
real ZK CAS only after a genuine test JVM SIGKILL. No signed business WAL
replay or new-Epoch READY is asserted by this stage test.

Never shares networks, ZooKeeper data or files with Order/Trade Demo.
"""
import argparse
import hashlib
import os
import pathlib
import secrets
import shutil
import subprocess
import time

ZK_IMAGE = "docker.m.daocloud.io/library/zookeeper:3.8.4"
DEMO_IMAGE = "dc-saas/gw:cluster-dev-fenced-transport-20261016"
ZOO_SERVERS = ("server.1=t376-zk1:2888:3888;2181 "
               "server.2=t376-zk2:2888:3888;2181 "
               "server.3=t376-zk3:2888:3888;2181")


def run(argv, timeout=35, env=None):
    return subprocess.run([str(a) for a in argv], capture_output=True,
                          text=True, env=env, timeout=timeout)


def compose_text(net_name):
    parts = ["services:"]
    for n in range(1, 4):
        parts.extend([
            "  zk"+str(n)+":",
            "    image: "+ZK_IMAGE,
            "    environment:",
            '      ZOO_MY_ID: "'+str(n)+'"',
            '      ZOO_SERVERS: "'+ZOO_SERVERS+'"',
            '      ZOO_4LW_COMMANDS_WHITELIST: "ruok,stat,mntr"',
            '      JVMFLAGS: "-Xms64m -Xmx256m"',
            "    networks:",
            "      isolated:",
            "        aliases:",
            "          - t376-zk"+str(n),
            "          - otc-t84-source-integrated-otc-ha-zk"+str(n)+"-1",
        ])
    parts.extend(["networks:", "  isolated:", "    name: "+net_name])
    return "\n".join(parts)+"\n"
TEST_RSA_WITNESS_GENERATOR = r"""
import java.nio.file.*;
import java.security.*;
import java.util.*;
public class T376IsolatedWitnessKeys {
 public static void main(String[] args) throws Exception {
  Path root=Paths.get(args[0]);
  Path[] privateFiles={
    root.resolve("a/node.pk8"),
    root.resolve("b/node.pk8"),
    root.resolve("c/node.pk8")};
  Path[] publicFiles={
    root.resolve("public/CommonHaDemoA.pub.der"),
    root.resolve("public/CommonHaDemoB.pub.der"),
    root.resolve("public/CommonHaDemoC.pub.der")};
  boolean all=true,any=false;
  for(Path p:privateFiles){all&=Files.isRegularFile(p);any|=Files.exists(p);}
  for(Path p:publicFiles){all&=Files.isRegularFile(p);any|=Files.exists(p);}
  if(all){System.out.println("T376_WITNESS_TEST_RSA_REUSED");return;}
  if(any)throw new IllegalStateException("partial test keys; no overwrite allowed");
  KeyPairGenerator generator=KeyPairGenerator.getInstance("RSA");
  generator.initialize(2048);
  for(int i=0;i<3;i++){
   Files.createDirectories(privateFiles[i].getParent());
   Files.createDirectories(publicFiles[i].getParent());
   KeyPair pair=generator.generateKeyPair();
   Files.write(privateFiles[i],pair.getPrivate().getEncoded(),StandardOpenOption.CREATE_NEW);
   Files.write(publicFiles[i],pair.getPublic().getEncoded(),StandardOpenOption.CREATE_NEW);
   Files.setPosixFilePermissions(privateFiles[i],
         java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
  }
  System.out.println("T376_ISOLATED_A_B_C_TEST_RSA_CREATED");
 }
}
"""


def run_real_256_home_control(wt, demo, jar, network, evidence, suffix):
    """One signed Home CAS with 255 untouched shards and B in a distinct JVM.

    This proves real ZooKeeper 256-shard MANIFEST control only; it neither
    synthesizes STRICT READY nor installs 256 physical customer WAL files.
    """
    keys=wt/"target/t375-isolated-test-identity"
    java_class=demo/"target/test-classes/com/app/common/replication/CommonT377Real256HomeStageProcess.class"
    if not java_class.is_file() or not (keys/"a/node.pk8").is_file():
        raise RuntimeError("T377 isolated 256-Home class or test-only A key missing")
    data=evidence/("t377-home-signed-"+suffix)
    data.mkdir(parents=True,exist_ok=False)
    zk_root="/dc/cluster/t377-"+suffix
    b_name="otc-t377-old-b-"+suffix
    clazz="com.app.common.replication.CommonT377Real256HomeStageProcess"
    cp="/t377/demo-test:/t377/demo:/t377/common.jar:/srv/dc/dc/GW/lib/*"
    mounts=["-v",str(jar)+":/t377/common.jar:ro",
            "-v",str(demo/"target/classes")+":/t377/demo:ro",
            "-v",str(demo/"target/test-classes")+":/t377/demo-test:ro"]
    env=["-e","OTC_T377_ZK_ROOT="+zk_root]
    def cmd(action, extra=None, name=None):
        opts=["docker","run"]
        if name:opts+=["-d","--name",name]
        else:opts+=["--rm"]
        opts+=["--network",network]+mounts+env
        if extra:opts+=extra
        return opts+["--entrypoint","java",DEMO_IMAGE,"-cp",cp,clazz,action]
    bootstrap=run(cmd("--bootstrap"),timeout=40)
    if bootstrap.returncode or "T377_256_SHARD_REAL_ZK_INITIAL_READY=PASS" not in bootstrap.stdout:
        raise RuntimeError("T377 bootstrap: "+bootstrap.stdout[-650:]+bootstrap.stderr[-600:])
    b_started=False
    try:
        b=run(cmd("--old-owner",name=b_name),timeout=24)
        if b.returncode:
            raise RuntimeError("separate B JVM failed: "+b.stderr[-700:])
        b_started=True
        old_live=False
        for _ in range(35):
            logs=run(["docker","logs",b_name],timeout=10)
            if "T377_OLD_B_PRIMARY_IN_SEPARATE_JVM_LEASE_ACTIVE=PASS" in logs.stdout:
                old_live=True
                break
            time.sleep(.4)
        if not old_live:raise RuntimeError("B primary did not preserve lease")
        # First test the real automatic Home scheduler. Without independent
        # signed physical catchup it must refuse ALL 128 Home partitions,
        # leaving the original 256 READY manifest and B's live lease intact.
        denied=run(cmd("--watch-no-physical",extra=[
            "-v",str(keys/"public")+":/rsa/public:ro",
            "-v",str(keys/"a/node.pk8")+":/rsa/a/node.pk8:ro",
            "-v",str(data)+":/srv/t377-durable-stage:rw"]),timeout=85)
        if denied.returncode or (
                "T378_REAL_3ZK_128_AUTO_HOME_WATCH_MISSING_WAL_DENIED_PASS"
                not in denied.stdout):
            raise RuntimeError("T378 real auto Home Watch failed to refuse "
                               "missing signed WAL; stdout="+denied.stdout[-650:]+
                               " stderr="+denied.stderr[-650:])
        staged=run(cmd("--real-home-stage",extra=[
            "-v",str(keys/"public")+":/rsa/public:ro",
            "-v",str(keys/"a/node.pk8")+":/rsa/a/node.pk8:ro",
            "-v",str(data)+":/srv/t377-durable-stage:rw"]),timeout=90)
        text=bootstrap.stdout+logs.stdout+denied.stdout+"\n"+denied.stderr+"\n"+staged.stdout+"\n"+staged.stderr
        stage_log=evidence/("t377-home-control-"+suffix+".log")
        stage_log.write_text(text)
        if staged.returncode:
            raise RuntimeError("T377 stage failed; evidence="+str(stage_log)+
                               " stdout="+staged.stdout[-900:]+" stderr="+staged.stderr[-700:])
        required=("T377_REAL_3ZK_256_HOME_FIRST_RSA_STAGE_PASS",
                  "T377_256_HOME_PARTIAL_CENSUS_PASS")
        if any(x not in text for x in required):
            raise RuntimeError("T377 stage omitted real 256 shard evidence")
        # The first A JVM has exited. Recover the same signed stage using
        # a different A JVM and independently issued ZooKeeper session.
        resumed=run(cmd("--resume-home",extra=[
            "-v",str(keys/"public")+":/rsa/public:ro",
            "-v",str(keys/"a/node.pk8")+":/rsa/a/node.pk8:ro",
            "-v",str(data)+":/srv/t377-durable-stage:rw"]),timeout=85)
        text+="\n"+resumed.stdout+"\n"+resumed.stderr
        stage_log.write_text(text)
        if resumed.returncode or (
                "T377_HOME_RSA_PREDECESSOR_NEW_A_SESSION_RESTORED=PASS"
                not in resumed.stdout):
            raise RuntimeError("T377 signed pending stage failed after A restart; "
                               "evidence="+str(stage_log)+
                               " stderr="+resumed.stderr[-600:])
        print("T377_REAL_256_HOME_CONTROL",stage_log,flush=True)
        for line in (denied.stdout+"\n"+staged.stdout+"\n"+resumed.stdout).splitlines():
            if line.startswith(("T377_","LIMITATION:")):
                print(line,flush=True)
        return resumed
    finally:
        if b_started:
            stopped=run(["docker","rm","-f",b_name],timeout=20)
            print("T377_ISOLATED_OLD_B_STOPPED",stopped.returncode==0,flush=True)


def run_real_256_signed_auto_control(wt, demo, jar, network, evidence, suffix, partition, watch_pressure=False, serial_home=None, continuous_writes=False):
    """Separate Docker JVMs fsync and RSA-sign test P000 WAL, then Common
    Watch automatically stages only P000. Does not claim physical old-B
    retirement or signed STRICT READY.
    """
    keys=wt/"target/t375-isolated-test-identity"
    required=(keys/"a/node.pk8",keys/"b/node.pk8",
              keys/"public/CommonHaDemoA.pub.der",keys/"public/CommonHaDemoB.pub.der")
    for p in required:
        if not p.is_file():raise RuntimeError("missing test-only RSA identity "+str(p))
    phys=evidence/("t378-physical-"+suffix)
    a=phys/"a";b=phys/"b"
    if continuous_writes:
        # Mac Docker Desktop bind mounts may delay visibility of a newly
        # fsynced hard link. Use genuinely independent Docker-managed
        # physical A and B volumes for both WAL and Genesis, as in T398.
        # Preserve both volumes after the run for independent forensic audit.
        a="otc-t400-"+suffix+"-a"
        b="otc-t400-"+suffix+"-b"
        for volume in (a,b):
            created=run(["docker","volume","create",volume],timeout=35)
            if created.returncode:
                raise RuntimeError("T400 physical evidence volume unavailable")
        print("T400_REAL_DOCKER_PHYSICAL_VOLUME_A",a,flush=True)
        print("T400_REAL_DOCKER_PHYSICAL_VOLUME_B",b,flush=True)
    else:
        a.mkdir(parents=True,exist_ok=False);b.mkdir(parents=True,exist_ok=False)
    clazz="com.app.common.replication.CommonT378RealWalAutoHomeProcess"
    bootstrap_clazz="com.app.common.replication.CommonT377Real256HomeStageProcess"
    cp="/t378/demo-test:/t378/demo:/t378/common.jar:/srv/dc/dc/GW/lib/*"
    mounts=["-v",str(jar)+":/t378/common.jar:ro",
            "-v",str(demo/"target/classes")+":/t378/demo:ro",
            "-v",str(demo/"target/test-classes")+":/t378/demo-test:ro",
            "-v",str(keys/"public")+":/rsa/public:ro"]
    partitions=serial_home or [partition]
    env=["-e","OTC_T377_ZK_ROOT=/dc/cluster/t377-"+suffix,
         "-e","OTC_T385_PARTITION="+partition,
         "-e","OTC_T388_128_WATCHES="+("true" if watch_pressure else "false")]
    if serial_home:
        env.extend(["-e","OTC_T390_HOME_PARTITIONS="+",".join(partitions)])
    if continuous_writes:
        if not serial_home:
            raise RuntimeError("T400 live-shard test needs multi-partition Home plan")
        env.extend(["-e","OTC_T400_CONTINUOUS_WRITES=true"])
    def command(action,klass=clazz,extra=None,name=None):
        opts=["docker","run"]
        if name:opts+=["-d","--name",name]
        else:opts+=["--rm"]
        opts+=["--network",network]+mounts+env
        if extra:opts+=extra
        return opts+["--entrypoint","java",DEMO_IMAGE,"-cp",cp,klass,action]
    seeded=run(command("--bootstrap",klass=bootstrap_clazz),timeout=40)
    if seeded.returncode or "T377_256_SHARD_REAL_ZK_INITIAL_READY=PASS" not in seeded.stdout:
        raise RuntimeError("isolated 256 original Home manifest creation failed: "+
                           seeded.stdout[-400:]+seeded.stderr[-500:])
    old_name="otc-t378-physical-b-"+suffix
    env.extend(["-e","OTC_T385_B_PEER="+old_name])
    old_up=False
    try:
        boot=run(command("--old-b",name=old_name,extra=[
            "-v",str(b)+":/srv/t378-b:rw",
            "-v",str(a)+":/srv/t378-a:ro",
            "-v",str(keys/"b/node.pk8")+":/rsa/b/node.pk8:ro"]),timeout=35)
        if boot.returncode:
            raise RuntimeError("old B writer JVM failed to start: "+boot.stderr[-650:])
        old_up=True
        signed=False
        for _ in range(45):
            logs=run(["docker","logs",old_name],timeout=10)
            if "T378_B_OLD_PRIMARY_ACTUAL_FSYNC_RSA_SIGNED_PASS" in logs.stdout:
                signed=True;break
            time.sleep(.3)
        if not signed:
            raise RuntimeError("old B did not prove real signed fsync WAL; "+
                               logs.stdout[-350:]+logs.stderr[-250:])
        result=run(command("--watch-a",extra=[
            "-v",str(a)+":/srv/t378-a:rw",
            "-v",str(b)+":/srv/t378-b:ro",
            "-v",str(keys/"a/node.pk8")+":/rsa/a/node.pk8:ro"]),timeout=max(95,70*len(partitions)))
        saved=evidence/("t378-signed-auto-home-"+suffix+".log")
        saved.write_text(seeded.stdout+"\n"+logs.stdout+"\n"+
                         result.stdout+"\n"+result.stderr)
        b_final=run(["docker","logs",old_name],timeout=10)
        if serial_home and result.returncode==0:
            for _ in range(60):
                if ("T390_SAME_JVM_SESSION_HOME_SERIES_PASS node=CommonHaDemoB"
                        in b_final.stdout):break
                time.sleep(.25)
                b_final=run(["docker","logs",old_name],timeout=10)
        saved.write_text(seeded.stdout+"\n"+b_final.stdout+"\n"+
                         b_final.stderr+"\n"+result.stdout+"\n"+result.stderr)
        if result.returncode or (
                "T378_REAL_TWO_JVM_DUAL_FSYNC_RSA_AUTO_HOME_STAGE_PASS"
                not in result.stdout) or (
                "T380_BOTH_OLD_E2_P000_REAL_FSYNC_WAL_RETIRED_RSA_PASS"
                not in result.stdout) or (
                "T380_B_P000_OLD_PRIMARY_REAL_WAL_CLOSED_RSA_RETIRED_PASS"
                not in b_final.stdout) or (
                "T381_B_E2_REAL_COMMITINDEX_CUSTODY_2_OF_2_FSYNC_PASS"
                not in b_final.stdout) or (
                "T381_E2_REAL_TWO_JVM_COMMITINDEX_CUSTODY_RSA_RECOVERY_SOURCE_PASS"
                not in result.stdout) or (
                "T382_B_E3_DUAL_RSA_SEALED_IMAGE_REOPEN_PASS"
                not in b_final.stdout) or (
                "T382_E3_TWO_REAL_VOTERS_RSA_FSYNC_SNAPSHOT_SEALED_PASS"
                not in result.stdout) or (
                "T383_E3_COMMON_TWO_JVM_REPLAY_AND_RECOVERY_RSA_BOTH_PASS"
                not in result.stdout) or (
                "T383_E3_CommonHaDemoB_REAL_COMMON_REPLAY_COMPLETE_RSA_RECEIPT_PASS"
                not in b_final.stdout) or (
                "T384_REAL_COMMON_AUTO_HOME_SIGNED_E3_STRICT_READY_PASS"
                not in result.stdout) or (
                "target="+partition+" epoch=3 newPrimary=A"
                not in result.stdout) or (
                "T385_E3_REAL_TCP_NEW_PRIMARY_A_TO_B_QUORUM_DURABLE_ACK_PASS"
                not in result.stdout) or (
                "T385_E3_B_NEW_WAL_TCP_FSYNC_PASS"
                not in b_final.stdout) or (
                watch_pressure and "T388_REAL_3ZK_128_HOME_WATCHES_WITH_ONE_PHYSICAL_STRICT_READY_PASS"
                not in result.stdout):
            raise RuntimeError("T378 dual RSA fsync Common auto Home failed, log="+
                               str(saved)+" stdout="+result.stdout[-800:]+
                               " stderr="+result.stderr[-700:]+
                               " b_stderr="+b_final.stderr[-1200:])
        if serial_home:
            import re
            def all_targets(log,marker):
                return re.findall(r"(?m)^"+re.escape(marker)+r".*?target=(P[0-9]{3})",log)
            staged=all_targets(result.stdout,"T390_SAME_ZK_HOME_STAGE_READY_PASS")
            if staged!=partitions:
                raise RuntimeError("T390 physical Home ordered READY != requested plan: "+
                                   str(staged)+" != "+str(partitions))
            for p in partitions:
                if ("partition="+p+" epoch=3 seq=1 clientAck=QUORUM_DURABLE"
                        not in result.stdout):
                    raise RuntimeError("T390 missing exact per-shard strict TCP ACK "+p)
            if continuous_writes:
                # Durability is checked AGAIN in the third independent JVM.
                for i in range(1,len(partitions)):
                    previous={partitions[0],partitions[i-1]}
                    for held in previous:
                        marker=("T400_E3_CONTINUOUS_QUORUM_DURABLE_ACK_PASS"
                                +" held="+held+" during="+partitions[i])
                        if marker not in result.stdout:
                            raise RuntimeError("T400 retained Home not writable: "+marker)
                if ("T400_A_PREVIOUS_HOME_REMAINED_WRITABLE_PASS"
                        not in result.stdout
                    or "T400_B_ALL_PRIOR_HOME_REPLICA_SERVERS_STAYED_LIVE_PASS"
                        not in b_final.stdout):
                    raise RuntimeError("T400 previous Home writers not continuously live")
                for shard in partitions:
                    if ("T400_REPLICA_STILL_LIVE_FSYNC_PASS shard="+shard
                            not in b_final.stdout):
                        raise RuntimeError("T400 B replica lost live shard "+shard)
                print("T400_SAME_ZK_PRIOR_READY_SHARDS_STAY_WRITABLE_PASS "
                    +"tested="+str(len(partitions))+" signedAck=QUORUM_DURABLE",
                    flush=True)
            for node,log in (("CommonHaDemoA",result.stdout),
                             ("CommonHaDemoB",b_final.stdout)):
                marker="T390_SAME_JVM_SESSION_HOME_SERIES_PASS node="+node
                if marker+" returned="+str(len(partitions)) not in log:
                    raise RuntimeError("T390 independent JVM did not complete "+node)
                sessions=re.findall(
                    r"(?m)^T390_SAME_ZK_SESSION node="+node+
                    r" session=(\d+) target=(P\d{3})",log)
                if [p for _,p in sessions]!=partitions or len(set(x for x,_ in sessions))!=1:
                    raise RuntimeError("T390 ZK session churn detected for "+node+
                                       " "+str(sessions))
            print("T390_TRUE_SAME_ZK_TWO_PARTITION_SIGNED_READY_TCP_ACK_PASS "+
                  "order="+",".join(partitions)+" ALease=CONTINUOUS BLease=CONTINUOUS",
                  flush=True)
        print("T378_REAL_RSA_FSYNC_AUTO_HOME_LOG",saved,flush=True)
        for line in result.stdout.splitlines()+b_final.stdout.splitlines():
            if line.startswith(("T378_","T380_","T381_","T382_","T383_","T384_","T385_","T388_","LIMITATION:")):print(line,flush=True)
        print("T385_REAL_RSA_COMMON_HOME_READY_E3_TCP_QUORUM_ACK_PASS",
              flush=True)
    finally:
        if old_up:
            killed=run(["docker","rm","-f",old_name],timeout=22)
            print("T378_ISOLATED_PHYSICAL_B_STOPPED",killed.returncode==0,flush=True)


    for audit_shard in partitions:
        audited=run(command("--audit",
            klass="com.app.common.replication.CommonT386PostHomeAckDiskAudit",
            extra=["-e","OTC_T385_PARTITION="+audit_shard,
                   "-v",str(a)+":/srv/t378-a:ro",
                   "-v",str(b)+":/srv/t378-b:ro"]),timeout=40)
        with saved.open("a") as evidence_append:
            evidence_append.write("\n"+audited.stdout+"\n"+audited.stderr)
        required="T386_INDEPENDENT_3RD_JVM_E3_REAL_TCP_DUAL_RSA_CUSTODY_PASS"
        if (audited.returncode or required not in audited.stdout
                or "partition="+audit_shard not in audited.stdout):
            raise RuntimeError("T390 per-shard third-JVM audit failed "+audit_shard+
                               " evidence="+str(saved)+" "+audited.stderr[-650:])
        print("T386_INDEPENDENT_READ_ONLY_RSA_CUSTODY_LOG",saved,flush=True)
        print(audited.stdout.strip(),flush=True)
    if serial_home:
        print("T390_SAME_ZK_ALL_HOME_PHYSICAL_THIRD_JVM_AUDIT_PASS "+
              "total="+str(len(partitions))+" shards="+",".join(partitions),
              flush=True)



def run_real_zk_historical_strict_ready(wt, demo, jar, network, evidence, suffix, fixture):
    """True ZooKeeper CAS of historical T293 physically signed evidence.
    No fabricated receipts; this is fixture-backed, NOT a live Home return.
    """
    fixture=fixture.resolve(strict=True)
    if not (fixture/"b/t298-e5-stage/P090-epoch-5.signed-stage").is_file():
        raise RuntimeError("T379 historical RSA stage fixture absent")
    if any(p.is_symlink() for p in fixture.rglob("*")):
        raise RuntimeError("T379 source fixture contains symlink")
    clone=evidence/("t379-signed-fixture-"+suffix)
    shutil.copytree(fixture,clone)
    clazz="com.app.common.replication.CommonT379RealZkStrictReadyFixtureProcess"
    cp="/t379/demo-test:/t379/demo:/t379/common.jar:/srv/dc/dc/GW/lib/*"
    mounts=["-v",str(jar)+":/t379/common.jar:ro",
            "-v",str(demo/"target/classes")+":/t379/demo:ro",
            "-v",str(demo/"target/test-classes")+":/t379/demo-test:ro",
            "-v",str(clone)+":/t379/signed:ro"]
    env=["-e","OTC_T379_RSA_FIXTURE=/t379/signed"]
    def command(mode,name=None):
        args=["docker","run"]
        if name:args+=["-d","--name",name]
        else:args+=["--rm"]
        args+=["--network",network]+mounts+env
        return args+["--entrypoint","java",DEMO_IMAGE,"-cp",cp,clazz,mode]
    seeded=run(command("--bootstrap"),timeout=55)
    if seeded.returncode or (
            "T379_REAL_3ZK_SIGNED_T293_STAGE_REPLAYED_FOR_FIXTURE_PASS"
            not in seeded.stdout):
        raise RuntimeError("T379 signed stage fixture preflight failed: "+
                           seeded.stdout[-700:]+seeded.stderr[-700:])
    replica="otc-t379-fixture-a-"+suffix
    started=False
    try:
        created=run(command("--replica-a",name=replica),timeout=30)
        if created.returncode:
            raise RuntimeError("T379 independent A session failed to start")
        started=True
        present=False
        for _ in range(40):
            logs=run(["docker","logs",replica],timeout=12)
            if "T379_REAL_ZK_REPLICA_A_DISTINCT_LIVE_SESSION_PASS" in logs.stdout:
                present=True;break
            time.sleep(.35)
        if not present:
            raise RuntimeError("T379 A distinct session absent; "+logs.stderr[-350:])
        published=run(command("--ready-b"),timeout=95)
        result=evidence/("t379-actual-strict-ready-"+suffix+".log")
        result.write_text(seeded.stdout+"\n"+logs.stdout+"\n"+
                          published.stdout+"\n"+published.stderr)
        if published.returncode or (
                "T379_REAL_ZK_T293_RSA_STRICT_READY_CAS_PASS"
                not in published.stdout):
            raise RuntimeError("T379 historical signed STRICT READY failed; "+
                               str(result)+" stdout="+published.stdout[-800:]+
                               " stderr="+published.stderr[-800:])
        print("T379_REAL_RSA_STRICT_READY_LOG",result,flush=True)
        for line in (seeded.stdout+"\n"+logs.stdout+"\n"+
                     published.stdout).splitlines():
            if line.startswith("T379_"):print(line,flush=True)
        print("T379_REAL_3ZK_HISTORICAL_RSA_CERTIFIED_READY_PASS "
              "fixture_backed_only=true live_home_not_claimed=true",flush=True)
    finally:
        if started:
            stopped=run(["docker","rm","-f",replica],timeout=25)
            print("T379_INDEPENDENT_REPLICA_A_STOPPED",stopped.returncode==0,flush=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--worktree",type=pathlib.Path,required=True)
    ap.add_argument("--base",type=pathlib.Path,required=True)
    ap.add_argument("--expected-sha256",required=True)
    ap.add_argument("--signed-fixture",type=pathlib.Path)
    ap.add_argument("--all-home-watch-pressure",action="store_true")
    ap.add_argument("--continuous-writes",action="store_true")
    ap.add_argument("--candidate-jar-name",choices=[
        "t377-common-home-auto-wiring.jar",
        "t389-common-cold-watch-proof-first.jar"])
    ap.add_argument("--home-partitions",default=None)
    ap.add_argument("--home-partition",default="P000")
    ap.add_argument("--mode",choices=["stage","signed-replay","signed-rejoin","signed-reverse","signed-cycle","home256","home256-signedwatch","historical-strict-ready"],default="stage")
    args=ap.parse_args()
    if (len(args.home_partition)!=4 or not args.home_partition.startswith("P")
            or not args.home_partition[1:].isdigit()
            or int(args.home_partition[1:])>127):
        raise RuntimeError("test Home partition must be P000–P127")
    serial_home=None
    if args.home_partitions:
        serial_home=args.home_partitions.split(",")
        if len(serial_home)<2 or len(serial_home)>128 or len(set(serial_home))!=len(serial_home):
            raise RuntimeError("T390 sequential Home must be 2 to 128 unique shards")
        numeric=[]
        for part in serial_home:
            if len(part)!=4 or part[0]!="P" or not part[1:].isdigit():
                raise RuntimeError("T390 invalid Home partition")
            numeric.append(int(part[1:]))
        if max(numeric)>127 or numeric!=sorted(numeric):
            raise RuntimeError("T390 only increasing original A Home supported")
        if args.mode!="home256-signedwatch":
            raise RuntimeError("T390 serial Home requires actual signed Watch test")
    if args.continuous_writes and serial_home is None:
        raise RuntimeError("T400 retained writers require explicit serial Home plan")
    wt=args.worktree.resolve(strict=True)
    base=args.base.resolve(strict=True)
    candidate=args.candidate_jar_name or (
        "t377-common-home-auto-wiring.jar" if args.mode.startswith("home256")
        or args.mode=="historical-strict-ready"
        else "t375-common-certified-automatic-recovery.jar")
    jar=wt/"target"/candidate
    if not jar.is_file():
        raise RuntimeError("no isolated Common T375 candidate")
    digest=hashlib.sha256(jar.read_bytes()).hexdigest()
    if digest!=args.expected_sha256:
        raise RuntimeError("Common candidate JAR digest mismatch; fail closed")
    demo=wt/"examples/common-only-demo"
    base_demo=base/"examples/common-only-demo"
    for relative in ("target/classes","target/test-classes"):
        dest=demo/relative
        if not dest.exists():
            shutil.copytree(base_demo/relative,dest)
    if not (demo/"target/test-classes/com/opentradingcore/demo/DemoCommonFailoverLiveZkStage.class").is_file():
        raise RuntimeError("compiled isolated live ZooKeeper witness missing")
    suffix=secrets.token_hex(4)
    project="otc-t376-"+suffix
    network=project+"-net"
    evidence=wt/"target/t376-isolated-zk"
    evidence.mkdir(parents=True,exist_ok=True)
    yaml=evidence/(project+".yaml")
    yaml.write_text(compose_text(network))
    call=["docker","compose","-p",project,"-f",yaml]
    for image in (ZK_IMAGE,DEMO_IMAGE):
        checked=run(["docker","image","inspect",image],timeout=30)
        if checked.returncode:
            raise RuntimeError("required preinstalled image not found: "+image)
    up=False
    try:
        print("T376_ISOLATED_DOCKER_NETWORK",network,flush=True)
        print("T376_PINNED_COMMON_SHA256",digest,flush=True)
        started=run(call+["up","-d","--pull","never"],timeout=90)
        if started.returncode:
            raise RuntimeError("independent ZooKeeper start failed:\n"+started.stderr[-1500:])
        up=True
        # ZooKeeper quorum startup is eventual; verify health without touching
        # any existing ZooKeeper Docker container or host-mapped port.
        ready=False
        for attempt in range(35):
            status=run(call+["ps","-q"],timeout=12)
            containers=[line for line in status.stdout.splitlines() if line.strip()]
            if status.returncode==0 and len(containers)==3:
                check=run(["docker","exec",containers[0],"bash","-c",
                           "echo ruok | nc -w 2 127.0.0.1 2181"],timeout=10)
                if "imok" in check.stdout:
                    ready=True
                    break
            time.sleep(1.5)
        if not ready:
            raise RuntimeError("three-node test ZooKeeper quorum did not report ruok")
        log=evidence/(project+".log")
        env=os.environ.copy()
        if args.mode=="historical-strict-ready":
            if args.signed_fixture is None:
                raise RuntimeError("T379 historical test requires original signed fixture")
            run_real_zk_historical_strict_ready(wt,demo,jar,network,evidence,
                                                suffix,args.signed_fixture)
            return
        if args.mode=="home256":
            result=run_real_256_home_control(wt,demo,jar,network,evidence,suffix)
            print("T377_256_HOME_REAL_CONTROL_ONLY_PASS signedReady_not_claimed=true",flush=True)
            return
        if args.mode=="home256-signedwatch":
            run_real_256_signed_auto_control(wt,demo,jar,network,evidence,
                                             suffix,serial_home[0] if serial_home else args.home_partition,
                                             args.all_home_watch_pressure,serial_home,
                                             args.continuous_writes)
            return
        if args.mode=="stage":
            env["OTC_T120_NETWORK"]=network
            env["OTC_T120_COMMON_JAR"]=str(jar)
            script=demo/"scripts/run-isolated-real-zk-failover-stage.sh"
        else:
            if args.mode in ("signed-rejoin","signed-reverse","signed-cycle"):
                test_keys=wt/"target/t376-physical-witness-identity"
                key_src=evidence/"T376IsolatedWitnessKeys.java"
                key_src.write_text(TEST_RSA_WITNESS_GENERATOR)
                built=run(["javac","-proc:none","-d",evidence,key_src],timeout=25)
                if built.returncode:
                    raise RuntimeError("test-only C signer generator failed:"+built.stderr[-300:])
                generated=run(["java","-cp",evidence,"T376IsolatedWitnessKeys",test_keys],timeout=35)
                if generated.returncode:
                    raise RuntimeError("test-only RSA identity creation failed:"+generated.stderr[-300:])
                print(generated.stdout.strip(),flush=True)
                env["OTC_T125_ENABLE_DEGRADED"]="1"
                env["OTC_T126_ENABLE_REJOIN"]="1"
                if args.mode in ("signed-reverse","signed-cycle"):
                    env["OTC_T127_ENABLE_REVERSE"]="1"
                    env["OTC_T128_REQUIRE_E3_INSTALL"]="1"
                if args.mode=="signed-cycle":
                    env["OTC_T129_REQUIRE_E3_WRITE"]="1"
                    env["OTC_T270_ENABLE_E3_B_REJOIN"]="1"
                    env["OTC_T272_ENABLE_TCP_AFTER_REJOIN"]="1"
            else:
                test_keys=wt/"target/t375-isolated-test-identity"
            if not (test_keys/"a/node.pk8").is_file() or not (test_keys/"b/node.pk8").is_file():
                raise RuntimeError("isolated test-only RSA A/B identities missing")
            env["OTC_EXISTING_DEMO_RSA_DIR"]=str(test_keys)
            env["OTC_T124_NETWORK"]=network
            env["OTC_T124_COMMON_JAR"]=str(jar)
            env["OTC_T124_AUTO_ROOT"]=str(wt/"target/t376-signed-replay-evidence")
            script=demo/"scripts/verify-real-auto-sigkill-genesis-replay.sh"
        with log.open("w") as f:
            result=subprocess.run(["bash",str(script)],env=env,stdout=f,
                                  stderr=subprocess.STDOUT,timeout=230)
        last=log.read_text(errors="replace").splitlines()
        for line in last[-65:]:
            if line.startswith(("T120_","T124_","LIMITATION:")):
                print(line,flush=True)
        print("T376_ISOLATED_LOG",log,flush=True)
        if result.returncode:
            raise RuntimeError("Common real-ZK stage test failed exit="+str(result.returncode)
                               +"; evidence log retained")
        if args.mode=="stage":
            expected=("T120_OLD_PRIMARY_STILL_RUNNING_STAGE_REJECTED=PASS",
                      "T120_REAL_ZK_OLD_PRIMARY_SESSION_RETIRED_PASS",
                      "T120_REAL_ZK_EPOCH_CAS_NO_PREMATURE_READY=PASS")
        else:
            expected=("T124_COMMON_WATCH_ARMED_BEFORE_PRIMARY_FAILURE=PASS",
                      "T124_REAL_E1_BUSINESS_UNDER_A_B_RSA_QUORUM_ACK=PASS",
                      "T124_REAL_SIGKILL_OLD_A_FULL_COMMON_DEMO_JVM=PASS",
                      "T124_END_TO_END_AUTO_STAGE_SIGNED_GENESIS_WAL_REPLAY=PASS")
            if args.mode in ("signed-rejoin","signed-reverse","signed-cycle"):
                expected+=("T125_AUTO_A_KILL_B_LOCAL_DURABLE_BUSINESS_CONTINUES=PASS",
                           "T126_A_RETURNED_AND_CAUGHT_UP_E1_AND_E2_BUSINESS=PASS")
            if args.mode=="signed-reverse":
                expected+=("T127_E2_B_KILLED_A_AUTOMATIC_E3_RECOVERING=PASS",
                           "T128_REAL_B_KILLED_A_FORMAL_SIGNED_GENESIS_AND_E1_E2_WAL_REPLAY_COMPLETE=PASS")
            if args.mode=="signed-cycle":
                expected+=("T127_B_REAL_SIGKILL_A_AUTO_E3_RECOVERING_PASS",
                           "T128_REAL_B_KILLED_A_FORMAL_SIGNED_GENESIS_AND_E1_E2_WAL_REPLAY_COMPLETE=PASS")
                expected+=("T129_TWO_REAL_SIGKILLS_A_B_A_CONTINUES_NEW_BUSINESS=PASS",
                           "T270_B_E3_ONLINE_REJOIN_RSA_PHYSICAL_AND_COMMON_ROLE=PASS",
                           "T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS")
        whole="\n".join(last)
        if any(marker not in whole for marker in expected):
            raise RuntimeError("real ZK signed recovery evidence missing")
        if args.mode=="stage":
            print("T376_REAL_ZK_SIGKILL_STAGE_PASS strict_READY_not_claimed=true",flush=True)
        elif args.mode=="signed-replay":
            print("T376_REAL_ZK_SIGKILL_RSA_WAL_REPLAY_PASS strict_READY_not_claimed=true",flush=True)
        elif args.mode=="signed-rejoin":
            print("T376_REAL_ZK_B_LOCAL_DURABLE_AND_A_REJOIN_PASS solo_ACK_possible_RPO=true",flush=True)
        elif args.mode=="signed-reverse":
            print("T376_REAL_ZK_TWO_WAY_SIGKILL_E3_REPLAY_PASS E3_READY_not_claimed=true",flush=True)
        else:
            print("T376_REAL_ZK_BOTH_DIRECTIONS_REJOIN_TCP_PASS solo_ACK_possible_RPO=true",flush=True)
    finally:
        if up:
            cleanup=run(call+["down","--remove-orphans"],timeout=65)
            print("T376_ISOLATED_ZK_STOPPED",cleanup.returncode==0,flush=True)


if __name__=="__main__":
    main()
