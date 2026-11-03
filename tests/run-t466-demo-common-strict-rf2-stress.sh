#!/usr/bin/env bash
# T466: real 3-ZooKeeper, TWO independent Common JVMs, Netty/RSA, signed
# CommitIndex + physical fsync + custody; 10/50/200 simulated tenant keys.
# ONLY the original STRICT_QUORUM E1. Never call LOCAL E2/E3 "strict".
# Does not touch existing Demo business containers, WAL or ZooKeeper namespace.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common="$repo/.work/t449-common-gw-rejoin"
demo="$common/examples/common-only-demo"
J="${OTC_T466_COMMON_JAR:-$common/target/t465-common-real-physical-sources.jar}"
K="${OTC_T466_RSA_DIR:-$repo/.work/t374-demo-common-ha/target/t376-physical-witness-identity}"
CLASS="$demo/target/t466-isolated-stress-classes"
IMAGE="${OTC_T466_IMAGE:-dc-saas/gw:cluster-dev-fenced-transport-20261016}"
NETWORK="${OTC_T466_NETWORK:-otc-t84-source-integrated-net}"
STAGES="${OTC_T466_STAGES:-10:100:1,50:200:4,200:400:8,200:400:8}"
stamp="$(date -u '+%Y%m%d%H%M%S')"
RUN="$stamp-$$"
A="otc-t466-strict-a-$RUN"
B="otc-t466-strict-b-$RUN"
ZK="/dc/cluster/t117-t466-$RUN"
ROOT="$repo/.work/t466-common-rf2-stress/$RUN"
mkdir -p "$ROOT/a" "$ROOT/b"
[[ -f "$J" && -d "$CLASS" && -f "$K/a/node.pk8" && -f "$K/b/node.pk8" ]] ||
    { echo 'T466_JAR_CLASSES_RSA_NOT_PROVISIONED' >&2;exit 2;}
[[ "$STAGES" =~ ^[0-9:,]+$ && "${#STAGES}" -le 400 ]] ||
    { echo 'T466_STAGES_UNSAFE' >&2;exit 2;}
docker image inspect "$IMAGE" >/dev/null
docker network inspect "$NETWORK" >/dev/null
cp "$J" "$ROOT/common-tested-pin.jar"
chmod a-w "$ROOT/common-tested-pin.jar"
shasum -a 256 "$ROOT/common-tested-pin.jar" | tee "$ROOT/common-sha256.txt"
J="$ROOT/common-tested-pin.jar"
echo "$STAGES" > "$ROOT/stages.txt"
echo "$ZK" > "$ROOT/zk-namespace.txt"
cleanup() {
    docker logs "$B" > "$ROOT/b.log" 2>&1 || :
    docker logs "$A" > "$ROOT/a-container.log" 2>&1 || :
    docker rm -f "$A" "$B" >/dev/null 2>&1 || :
}
trap cleanup EXIT
# Only this run's immutable Common binary and test-generated classes are mounted.
# Neither run obtains original live Order/Trade data or container volume paths.
CP='/t466/demo-test:/t117/demo-test:/t117/demo:/t117/common.jar:/srv/dc/dc/GW/lib/*'
MOUNTS=(-v "$J:/t117/common.jar:ro"
        -v "$CLASS:/t466/demo-test:ro"
        -v "$demo/target/classes:/t117/demo:ro"
        -v "$demo/target/test-classes:/t117/demo-test:ro"
        -v "$K/public:/rsa/public:ro")
ENV=(-e "OTC_T117_ZK_ROOT=$ZK"
     -e "OTC_T117_PEER_A=$A" -e "OTC_T117_PEER_B=$B")
docker run --rm --network "$NETWORK" "${MOUNTS[@]}" "${ENV[@]}" \
    --entrypoint java "$IMAGE" -Xms128m -Xmx640m -cp "$CP" \
    com.opentradingcore.demo.DemoCommonLiveZkProcess --bootstrap \
    >"$ROOT/bootstrap.log" 2>&1
grep '^T117_TEST_ONLY_ZK_MANIFEST_READY' "$ROOT/bootstrap.log"
docker run -d --name "$B" --network "$NETWORK" "${MOUNTS[@]}" "${ENV[@]}" \
    -e OTC_T466_REPLICA_HOLD_MS=240000 \
    -v "$K/b/node.pk8:/rsa/b/node.pk8:ro" \
    -v "$ROOT/b:/srv/t117-data:rw" \
    --entrypoint java "$IMAGE" -Xms128m -Xmx640m -cp "$CP" \
    com.opentradingcore.demo.DemoCommonLiveZkProcess --node=B >/dev/null
ready=false
for i in $(seq 1 100);do
    if docker logs "$B" 2>&1 | grep 'T117_REAL_ZK_COMMON_NODE_UP=CommonHaDemoB role=REPLICA' >/dev/null;then
        ready=true;break
    fi
    [[ "$(docker inspect "$B" --format '{{.State.Running}}')" == true ]] ||
        { echo T466_REPLICA_JVM_EXITED;docker logs "$B";exit 3;}
    sleep .2
done
[[ "$ready" == true ]] ||
    { echo T466_REPLICA_READY_TIMEOUT;docker logs "$B";exit 3;}
echo 'T466_B_PHYSICAL_NETTY_REPLICA_ARMED_PASS'
set +e
docker run --rm --name "$A" --network "$NETWORK" "${MOUNTS[@]}" "${ENV[@]}" \
    -e "OTC_T466_STRICT_STAGES=$STAGES" \
    -v "$K/a/node.pk8:/rsa/a/node.pk8:ro" \
    -v "$ROOT/a:/srv/t117-data:rw" \
    --entrypoint java "$IMAGE" -Xms128m -Xmx640m -cp "$CP" \
    com.opentradingcore.demo.DemoCommonLiveZkProcess --node=A \
    >"$ROOT/a.log" 2>&1
exit_status=$?
set -e
grep '^T466_' "$ROOT/a.log" || :
if [[ "$exit_status" -ne 0 ]];then
    echo "T466_A_COMMON_LOAD_FAILED exit=$exit_status" >&2
    tail -65 "$ROOT/a.log" >&2
    exit "$exit_status"
fi
grep '^T466_ALL_STRICT_2_OF_2_STAGES_PASS' "$ROOT/a.log" >/dev/null ||
    { echo T466_NOT_ALL_STRICT_ACKED >&2;tail -45 "$ROOT/a.log";exit 5;}
# Wait until the B process's current WAL fsync covers the just-acknowledged
# final Common strict certificate. A returned quorum ACK is authoritative;
# the independent raw disk comparison detects silent divergence.
A_WAL="$ROOT/a/CommonHaDemo/CommonHaDemoA/P090/epoch-1/business.wal"
B_WAL="$ROOT/b/CommonHaDemo/CommonHaDemoB/P090/epoch-1/business.wal"
[[ -s "$A_WAL" && -s "$B_WAL" ]] || { echo T466_WAL_NOT_DURABLE;exit 6;}
cmp "$A_WAL" "$B_WAL" ||
    { echo T466_ORIGINAL_WAL_DIVERGENCE;exit 7;}
shasum -a 256 "$A_WAL" "$B_WAL" | tee "$ROOT/wal-sha256.txt"
T466_ROOT="$ROOT" python3 - <<'PY'
import os, pathlib, re, struct, json
root=pathlib.Path(os.environ['T466_ROOT'])
stages=[tuple(map(int,x.split(':'))) for x in (root/'stages.txt').read_text().strip().split(',')]
log=(root/'a.log').read_text()
results=[]
for line in log.splitlines():
    if not line.startswith('T466_RF2_STRICT_STRESS_STAGE '):continue
    kv=dict(x.split('=',1) for x in line.split()[1:] if '=' in x)
    for name in ['tenantsSimulated','writes','workers','acked','failures','firstSeq','endSeq','businessDelta']:
        kv[name]=int(kv[name])
    for name in ['tps','p50Ms','p95Ms','p99Ms','elapsedSec']:
        kv[name]=float(kv[name])
    if kv['validation']!='PASS' or kv['quorum']!='true' or kv['failures'] or kv['acked']!=kv['writes']:
        raise SystemExit('T466_STRICT_CLIENT_ACK_METRIC_INVALID')
    results.append(kv)
if len(results)!=len(stages) or [(r['tenantsSimulated'],r['writes'],r['workers']) for r in results]!=stages:
    raise SystemExit('T466_STAGES_INCOMPLETE')
sequence=0
for r in results:
    if r['firstSeq']!=3+sequence or r['endSeq']!=2+sequence+r['writes']:
        raise SystemExit('T466_SEQ_GAP_OR_DUPLICATE')
    sequence+=r['writes']
files=[root/p/'CommonHaDemo'/('CommonHaDemoA' if p=='a' else 'CommonHaDemoB')/'P090'/'epoch-1'/'business.wal' for p in ('a','b')]
for f in files:
    raw=f.read_bytes()
    offset=0
    for n in range(1,3+sequence):
        if len(raw)-offset<28:raise SystemExit('T466_TRUNCATED_WAL_FRAME')
        magic,epoch,seq,size,crc=struct.unpack('>Iqqii',raw[offset:offset+28])
        if epoch!=1 or seq!=n or size<=0 or size>16*1024*1024 or len(raw)-offset-28<size:
            raise SystemExit(f'T466_INVALID_PHYSICAL_WAL_SEQUENCE seq={n} actual={seq}')
        offset+=28+size
    if offset!=len(raw):raise SystemExit('T466_EXTRA_UNCERTIFIED_WAL_TAIL')
report={'scope':'Common Demo 2 physical JVMs, 3 live ZooKeeper; one P090 hotspot only',
        'durability':'STRICT_QUORUM, 2/2 physical independent fsync/custody',
        'not_actual_tenants':True, 'not_256_partition_stress':True,
        'docker_cpu_count':8,'stages':results,'total_stage_writes':sequence,
        'original_wal_frames_per_node':sequence+2,
        'acknowledgment_fully_verified':True}
(root/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'T466_STRICT_TWO_DISK_BITEXACT_ALL_FRAMES_PASS frames={sequence+2} independentNodes=2')
print('T466_METRICS='+str(root/'metrics.json'))
PY
echo "T466_DEMO_COMMON_RF2_STRESS_PASS evidence=$ROOT"