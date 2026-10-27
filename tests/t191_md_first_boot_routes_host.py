#!/usr/bin/env python3
"""Virgin Demo MD partition bootstrap exactly matching deploy-saas.sh.
Never overwrite/reconfigure any existing partition, and never mark a market
image READY: MdPartitionRuntime.canPublish separately requires actual full Order image.
"""
import subprocess,sys,re,json
root="/dc/cluster/mdsvr/partitions"
def cli(commands):
    result=subprocess.run(["docker","exec","-i",
      "-e","CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini",
      "dc-saas-zookeeper","zkCli.sh","-server","127.0.0.1:32181"],
      input=commands+"\nquit\n",text=True,stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,timeout=95)
    # zkCli exits 1 for an EXPECTED missing root and existing ancestors.
    # Never tolerate actual authentication or disconnected-session errors.
    if result.returncode not in (0,1) or any(err in result.stdout for err in
            ("KeeperErrorCode = NoAuth","KeeperErrorCode = ConnectionLoss",
             "KeeperErrorCode = SessionExpired","KeeperErrorCode = InvalidACL")):
        raise RuntimeError("ZK session/authorization failure: "+result.stdout[-380:])
    return result.stdout
def live(name):
    x=subprocess.run(["docker","inspect","--format","{{.State.Running}}",name],
        capture_output=True,text=True,check=True)
    return x.stdout.strip()=="true"
if not all(live("dc-saas-mdsvr"+n) for n in ("","-b")):
    raise SystemExit("T191_DENIED: both real MD JVMs must run first")
a=cli("ls "+root)
if "Node does not exist: "+root not in a:
    raise SystemExit("T191_DENIED: original MD directory already exists; no reset permitted")
for node in ("MDSvrA","MDSvrB"):
    out=cli("ls /MDTService/"+node)
    if "["+node+"]" not in out:
        raise SystemExit("T191_DENIED: original MD ZK session not live: "+node)
root_commands=['create /dc x','create /dc/cluster x','create /dc/cluster/mdsvr x','create '+root+' x']
for i in range(256):
    name="P%03d"%i
    primary="MDSvrA" if i%2==0 else "MDSvrB"
    replica="MDSvrB" if i%2==0 else "MDSvrA"
    assignment=dict(partitionId=name,epoch=1,primary=primary,replica=replica,state="READY")
    # This is initial route ownership ONLY. Per-market publish remains fenced
    # until a COMPLETE real Order Image is installed on the assigned primary.
    root_commands.append("create "+root+"/"+name+" "+json.dumps(assignment,separators=(",",":")))
created=cli("\n".join(root_commands))
if "NoAuth" in created or "ConnectionLoss" in created or "SessionExpired" in created:
    raise SystemExit("T191_DENIED: ZK client failed during create; preserve partial rows")
# original deploy creates parent nodes idempotently; conflicts only permitted in ancestors.
if "Node already exists: "+root+"/P" in created:
    raise SystemExit("T191_DENIED: unexpected partition conflict")
readback=cli("ls "+root)
rows=set(re.findall(r"\bP[0-9]{3}\b",readback))
if rows!={"P%03d"%i for i in range(256)}:
    raise SystemExit("T191_PARTIAL: actual created MD partitions "+str(len(rows))+"/256")
print("T191_MD_ROUTING_FIRST_BOOT_PASS partitions=256 primaries=A128+B128 marketImageReady=unverified")
