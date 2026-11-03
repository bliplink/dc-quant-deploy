#!/usr/bin/env bash
# T466 REAL 3ZK / 256 local shard census / 2 JVM A+B 128:128 Home:
# fully strict original-E1 physical WAL, RSA quorum and dual custody under load.
# Fresh isolated namespace/volumes only. No fault injection, no false READY
# claim: fresh Genesis here is TEST-ONLY, not production-certified startup.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common="$repo/.work/t449-common-gw-rejoin"
demo="$common/examples/common-only-demo"
J="${OTC_T466_COMMON_JAR:-$common/target/t465-common-real-physical-sources.jar}"
K="${OTC_T466_RSA_DIR:-$repo/.work/t374-demo-common-ha/target/t376-physical-witness-identity}"
CLASS="$demo/target/t466-isolated-stress-classes"
IMAGE="${OTC_T466_IMAGE:-dc-saas/gw:cluster-dev-fenced-transport-20261016}"
NET="${OTC_T466_NETWORK:-otc-t84-source-integrated-net}"
STAGES="${OTC_T466_256_STAGES:-10:20:1,50:50:2,200:200:4}"
RUN="$(date -u '+%Y%m%d%H%M%S')-$$"
ROOT="$repo/.work/t466-common-256-strict/$RUN"
ZK="/dc/cluster/t466-$RUN"
A="otc-t466-256-a-$RUN"
B="otc-t466-256-b-$RUN"
mkdir -p "$ROOT/a" "$ROOT/b"
[[ -s "$J" && -d "$CLASS" && -f "$K/a/node.pk8" && -f "$K/b/node.pk8" ]] ||
  { echo 'T466_256_NO_PINNED_COMMON_RSA_OR_CLASSES' >&2;exit 2;}
[[ "$STAGES" =~ ^[0-9:,]+$ && "${#STAGES}" -le 400 ]] ||
  { echo 'T466_256_STAGES_UNSAFE' >&2;exit 2;}
docker image inspect "$IMAGE" >/dev/null
docker network inspect "$NET" >/dev/null
cp "$J" "$ROOT/common-tested-pin.jar"
chmod a-w "$ROOT/common-tested-pin.jar"
J="$ROOT/common-tested-pin.jar"
shasum -a 256 "$J" | tee "$ROOT/common-sha256.txt"
echo "$STAGES" > "$ROOT/stages.txt"
echo "$ZK" > "$ROOT/zk-namespace.txt"
cleanup(){
  docker logs "$A" > "$ROOT/a.log" 2>&1 || :
  docker logs "$B" > "$ROOT/b.log" 2>&1 || :
  docker rm -f "$A" "$B" >/dev/null 2>&1 || :
}
trap cleanup EXIT
CP='/t466/demo-test:/t117/demo-test:/t117/demo:/t117/common.jar:/srv/dc/dc/GW/lib/*'
MOUNTS=(-v "$J:/t117/common.jar:ro"
 -v "$CLASS:/t466/demo-test:ro"
 -v "$demo/target/classes:/t117/demo:ro"
 -v "$demo/target/test-classes:/t117/demo-test:ro"
 -v "$K/public:/rsa/public:ro")
ENV=(-e "OTC_T466_256_ZK_ROOT=$ZK"
 -e "OTC_T466_256_PEER_A=$A" -e "OTC_T466_256_PEER_B=$B"
 -e "OTC_T466_256_STAGES=$STAGES")
docker run --rm --network "$NET" "${MOUNTS[@]}" "${ENV[@]}" \
 --entrypoint java "$IMAGE" -Xms192m -Xmx1400m -cp "$CP" \
 com.opentradingcore.demo.DemoCommon256StrictProcess --bootstrap \
 > "$ROOT/bootstrap.log" 2>&1 ||
 { tail -60 "$ROOT/bootstrap.log" >&2;exit 3;}
grep '^T466_256_ISOLATED_FULL_HOME_ZK_GENESIS_CREATED' "$ROOT/bootstrap.log"
docker run -d --name "$A" --network "$NET" "${MOUNTS[@]}" "${ENV[@]}" \
 -v "$K/a/node.pk8:/rsa/a/node.pk8:ro" -v "$ROOT/a:/srv/t466-data:rw" \
 --entrypoint java "$IMAGE" -Xms192m -Xmx1400m -cp "$CP" \
 com.opentradingcore.demo.DemoCommon256StrictProcess --node=A >/dev/null
docker run -d --name "$B" --network "$NET" "${MOUNTS[@]}" "${ENV[@]}" \
 -v "$K/b/node.pk8:/rsa/b/node.pk8:ro" -v "$ROOT/b:/srv/t466-data:rw" \
 --entrypoint java "$IMAGE" -Xms192m -Xmx1400m -cp "$CP" \
 com.opentradingcore.demo.DemoCommon256StrictProcess --node=B >/dev/null
echo 'T466_256_BOTH_PHYSICAL_JVMS_STARTED'
finished=false
for i in $(seq 1 850);do
  if docker logs "$A" 2>&1 | grep '^T466_256_NODE_128_HOME_STRICT_ALL_STAGES_PASS' >/dev/null &&
     docker logs "$B" 2>&1 | grep '^T466_256_NODE_128_HOME_STRICT_ALL_STAGES_PASS' >/dev/null;then
    finished=true;break
  fi
  for node in "$A" "$B";do
    if [[ "$(docker inspect "$node" --format '{{.State.Running}}')" != true ]];then
       echo "T466_256_JVM_EXITED_BEFORE_STRESS_COMPLETE $node" >&2
       docker logs "$node" | tail -65 >&2
       exit 4
    fi
  done
  sleep .35
done
[[ "$finished" == true ]] || {
  echo T466_256_RUNTIME_TIMEOUT >&2
  docker logs "$A" | tail -65 >&2
  docker logs "$B" | tail -65 >&2
  exit 5
}
docker logs "$A" > "$ROOT/a.log" 2>&1
docker logs "$B" > "$ROOT/b.log" 2>&1
grep '^T466_256_STRICT_STAGE' "$ROOT/a.log" "$ROOT/b.log"
T466_ROOT="$ROOT" python3 - <<'PY'
import os,pathlib,struct,hashlib,json
root=pathlib.Path(os.environ['T466_ROOT'])
stages=[tuple(map(int,x.split(':'))) for x in (root/'stages.txt').read_text().strip().split(',')]
stats=[]
for node in ('a','b'):
    lines=(root/(node+'.log')).read_text(errors='replace').splitlines()
    if not any('T466_256_NODE_128_HOME_STRICT_ALL_STAGES_PASS' in x for x in lines):
        raise SystemExit('T466_256_MISSING_BOTH_COMMITTED_MARKERS')
    node_stats=[]
    for line in lines:
        if not line.startswith('T466_256_STRICT_STAGE '):continue
        d=dict(x.split('=',1) for x in line.split()[1:] if '=' in x)
        for k in ('tenantsSimulated','writes','workers','acked','failed','homePrimaries','totalBusiness'):
            d[k]=int(d[k])
        for k in ('tps','p50Ms','p95Ms','p99Ms','elapsedSec'):d[k]=float(d[k])
        if d['failed'] or d['acked']!=d['writes'] or d['validation']!='PASS' or d['strict']!='true':
            raise SystemExit('T466_256_FAKE_STRICT_CLIENT_ACK')
        node_stats.append(d)
    if len(node_stats)!=len(stages) or [(x['tenantsSimulated'],x['writes'],x['workers']) for x in node_stats]!=stages:
        raise SystemExit('T466_256_MISSING_LOAD_STAGES')
    if node_stats[-1]['totalBusiness']!=sum(s[1] for s in stages):
        raise SystemExit('T466_256_DOMAIN_TOTAL_MISMATCH')
    stats.extend(node_stats)
total_frames=0
per_partition={}
for partition in range(256):
    pid=f'P{partition:03d}'
    data=[]
    frames=None
    for node,name in [('a','CommonHaDemoA'),('b','CommonHaDemoB')]:
        path=root/node/'CommonHaDemo'/name/pid/'epoch-1'/'business.wal'
        if not path.is_file():raise SystemExit('T466_256_MISSING_PHYSICAL_WAL '+str(path))
        raw=path.read_bytes()
        offset=0;seq=0
        while offset<len(raw):
            if len(raw)-offset<28:raise SystemExit('T466_256_TRUNCATED_WAL')
            magic,epoch,n,size,crc=struct.unpack('>Iqqii',raw[offset:offset+28])
            if epoch!=1 or n!=seq+1 or size<=0 or size>16*1024*1024 or len(raw)-offset-28<size:
                raise SystemExit('T466_256_DIVERGENT_FRAME '+pid)
            seq=n;offset+=28+size
        data.append(hashlib.sha256(raw).hexdigest())
        if frames is None:frames=seq
        elif frames!=seq:raise SystemExit('T466_256_INDEPENDENT_WAL_FRAME_COUNT_MISMATCH '+pid)
    if data[0]!=data[1]:
        raise SystemExit('T466_256_INDEPENDENT_PHYSICAL_A_B_WAL_DIVERGENCE '+pid)
    total_frames+=frames
    per_partition[pid]={'frames':frames,'sha256':data[0]}
expected=sum(s[1] for s in stages)*2
if total_frames!=expected:raise SystemExit('T466_256_CROSS_SHARD_ACK_GAP_OR_DUPLICATE '+str(total_frames)+' / '+str(expected))
summary={'scope':'256 partitions, two physical Common JVMs, 3 ZooKeeper, 128:128 Home',
  'test_genesis_only':True,'customer_e2_e3_ready_not_claimed':True,
  'durability':'strict 2/2 RSA+CommitIndex+dual custody per acknowledged write',
  'cpu_limit':'Docker 8 CPUs shared with live Demo workloads',
  'stages':stats,'total_acknowledged_writes':expected,
  'bit_exact_full_physical_partition_count':256,
  'bit_exact_original_wal_frame_count':total_frames,
  'all_256_partition_hashes':per_partition}
(root/'metrics.json').write_text(json.dumps(summary,indent=2)+'\n')
print(f'T466_256_REAL_A_B_256_PARTITIONS_BITEXACT_PASS frames={total_frames} partitions=256')
print('T466_256_METRICS='+str(root/'metrics.json'))
PY
echo "T466_256_STRICT_TWO_JVM_STRESS_PASS evidence=$ROOT"
