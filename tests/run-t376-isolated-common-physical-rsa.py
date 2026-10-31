#!/usr/bin/env python3
"""T376: isolated Common/physical RSA regression with exact candidate jar.

Never reads production RSA. Never mutates Order/Trade or ZK.
Generates private test-only A/B keys under the isolated working tree's target
directory only if no keys already exist, and a third public-only C identity.
Fails if tests are skipped, fail, or the required suite is not executed.
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile

SUITES = (
    "CommonAutoRecoveryPlanCoverageTest",
    "CommonFailoverControlSharedSchedulerTest",
    "CommonCertifiedFailoverCoordinatorTest",
    "CommonCertifiedStrictCrashReadyCompletionTest",
    "CommonCertifiedNodeRuntimeTest",
    "CommonHomeReturnCensusTest",
    "CommonCertifiedIndependentWitnessWatchTest",
)

KEY_HELPER = r"""
import java.nio.file.*;import java.security.*;
public final class T376TestIdentities {
    public static void main(String[] args) throws Exception {
        Path root=Paths.get(args[0]);
        Path a=root.resolve("a/node.pk8"),b=root.resolve("b/node.pk8");
        Path pa=root.resolve("public/CommonHaDemoA.pub.der"),
             pb=root.resolve("public/CommonHaDemoB.pub.der"),
             pc=root.resolve("public/CommonHaDemoC.pub.der");
        boolean all=Files.exists(a)&&Files.exists(b)
                 &&Files.exists(pa)&&Files.exists(pb)&&Files.exists(pc);
        boolean any=Files.exists(a)||Files.exists(b)
                 ||Files.exists(pa)||Files.exists(pb)||Files.exists(pc);
        if(all){System.out.println("T376_TEST_KEYS_REUSED");return;}
        if(any)throw new IllegalStateException("partial test identity; refusal to overwrite");
        for(Path dir:new Path[]{a.getParent(),b.getParent(),pa.getParent()})
            Files.createDirectories(dir);
        KeyPairGenerator generator=KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        for(String n:new String[]{"CommonHaDemoA","CommonHaDemoB","CommonHaDemoC"}){
            KeyPair kp=generator.generateKeyPair();
            Files.write(root.resolve("public/"+n+".pub.der"),
                kp.getPublic().getEncoded(),StandardOpenOption.CREATE_NEW);
            if(!n.endsWith("C"))
                Files.write(root.resolve(n.endsWith("A")?"a/node.pk8":"b/node.pk8"),
                    kp.getPrivate().getEncoded(),StandardOpenOption.CREATE_NEW);
        }
        System.out.println("T376_TEST_ONLY_KEYS_CREATED A_B_PRIVATE_C_PUBLIC");
    }
}
"""

COUNT_HELPER = r"""
import org.junit.runner.*;
import org.junit.runner.notification.*;
public final class T376JUnitCount {
 public static void main(String[] args)throws Exception{
  Class<?>[] classes=new Class<?>[args.length];
  for(int i=0;i<args.length;i++)
      classes[i]=Class.forName("com.app.common.replication."+args[i]);
  final int[] skipped={0};
  JUnitCore runner=new JUnitCore();
  runner.addListener(new RunListener(){
      @Override public void testAssumptionFailure(Failure f){
          skipped[0]++;
          System.out.println("T376_SKIPPED "+f.getTestHeader()+" REASON="+f.getMessage());
      }
  });
  Result result=runner.run(classes);
  for(Failure failure:result.getFailures())
      System.out.println("FAIL "+failure.getTestHeader()+" "+failure.getMessage());
  int executed=result.getRunCount()-skipped[0]-result.getIgnoreCount();
  System.out.println("T376_PHYSICAL_RSA_SUITE discovered="+result.getRunCount()
    +" executed="+executed+" assumption_skips="+skipped[0]
    +" ignored="+result.getIgnoreCount()+" failures="+result.getFailureCount());
  if(result.getRunCount()!=42 || executed!=42 || skipped[0]!=0
       ||result.getIgnoreCount()!=0 ||!result.wasSuccessful())System.exit(2);
 }
}
"""

def run(argv, timeout=80):
    result = subprocess.run([str(x) for x in argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("command failed (code="+str(result.returncode)+"): "+
            result.stdout[-2800:]+"\n"+result.stderr[-1200:])
    return result.stdout.strip()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--worktree",type=pathlib.Path,required=True)
    p.add_argument("--base",type=pathlib.Path,required=True)
    p.add_argument("--signed-fixture",type=pathlib.Path,required=True,
                   help="original T293 TEST fixture, copied read-only before test")
    args=p.parse_args()
    worktree=args.worktree.resolve(strict=True)
    base=args.base.resolve(strict=True)
    jar=worktree/"target/t375-common-certified-automatic-recovery.jar"
    if not jar.is_file() or not (base/"target/test-classes").is_dir():
        raise RuntimeError("isolated candidate jar or baseline test classes missing")
    print("T376_PINNED_COMMON_SHA256",hashlib.sha256(jar.read_bytes()).hexdigest(),flush=True)
    keys=worktree/"target/t375-isolated-test-identity"
    # Never reference actual business keys.
    if not str(keys.resolve()).startswith(str((worktree/"target").resolve())+os.sep):
        raise RuntimeError("test identities outside isolated target")
    signed=args.signed_fixture.resolve(strict=True)
    if not signed.is_dir() or any(p.is_symlink() for p in signed.rglob("*")):
        raise RuntimeError("signed test fixture missing or contains symlinks")
    if not (signed/"shared/e5-sealed").is_dir():
        raise RuntimeError("T293 sealed historical TEST fixture is missing")
    with tempfile.TemporaryDirectory(prefix="t376-junit-",dir=worktree/"target") as d:
        tmp=pathlib.Path(d)
        cloned=tmp/"signed-fixture"
        shutil.copytree(signed,cloned)
        print("T376_SIGNED_RSA_FIXTURE_CLONED original_untouched=true",flush=True)
        helper=tmp/"T376TestIdentities.java"
        helper.write_text(KEY_HELPER)
        run(["javac","-proc:none","-d",tmp,helper])
        print(run(["java","-cp",tmp,"T376TestIdentities",keys]),flush=True)
        helper=tmp/"T376JUnitCount.java"
        helper.write_text(COUNT_HELPER)
        repo=pathlib.Path.home()/".m2/repository"
        slf4j=repo/"org/slf4j"
        pinned=[
            slf4j/"slf4j-api/1.7.30/slf4j-api-1.7.30.jar",
            slf4j/"slf4j-log4j12/1.7.30/slf4j-log4j12-1.7.30.jar"
        ]
        for dep in pinned:
            if not dep.is_file():
                raise RuntimeError("missing pinned dependency "+str(dep))
        others=sorted(str(x) for x in repo.rglob("*.jar")
                      if not str(x).startswith(str(slf4j)+os.sep)
                      and "logback-classic" not in x.name)
        classpath=os.pathsep.join([str(worktree/"target/test-classes"),str(jar),
            str(base/"target/test-classes")]+[str(x) for x in pinned]+others)
        run(["javac","-proc:none","-cp",classpath,"-d",tmp,helper])
        print(run(["java","-Dotc.demo.existing.keys="+str(keys),
                   "-Dotc.t322.real.root="+str(cloned),
                   "-cp",str(tmp)+os.pathsep+classpath,"T376JUnitCount"]+list(SUITES),timeout=210),flush=True)

if __name__=="__main__":
    main()
