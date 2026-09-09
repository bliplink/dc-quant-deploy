#!/usr/bin/env bash
set -euo pipefail

ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
ZK_CONTAINER="${ZOOKEEPER_CONTAINER:-dc-saas-cluster-zookeeper}"
ZK_ENDPOINT="${ZOOKEEPER_ENDPOINT:-127.0.0.1:32182}"
GW_HOST="${ORDER_CLUSTER_GW_HOST:-127.0.0.1}"
GW_PORT="${ORDER_CLUSTER_GW_PORT:-33302}"
REQUESTS="${ORDER_CLUSTER_PERF_REQUESTS:-2000}"
CONCURRENCY="${ORDER_CLUSTER_PERF_CONCURRENCY:-32}"
WARMUP="${ORDER_CLUSTER_PERF_WARMUP:-200}"
SEQUENCE="${ORDER_CLUSTER_PERF_SEQUENCE:-ABBA}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD_SCRIPT="${SCRIPT_DIR}/order-cluster-throughput-load.py"
P027="/dc/cluster/ordersvr-dev/partitions/P027"
P132="/dc/cluster/ordersvr-dev/partitions/P132"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EVIDENCE="${ROOT}/evidence/${RUN_ID}-throughput"
LOG_A="${ROOT}/log/OrderSvrA.log"
LOG_B="${ROOT}/log/OrderSvrB.log"
BASE_EPOCH="$(date +%s%N | cut -c1-15)"
RESTORE=false

log() { printf '[order-cluster-throughput] %s\n' "$*"; }
die() { printf '[order-cluster-throughput] ERROR: %s\n' "$*" >&2; exit 1; }
zk() { printf '%s\nquit\n' "$1" | sudo docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_ENDPOINT}" 2>/dev/null; }
read_assignment() { zk "get $1" | grep -E '^\{"partitionId"' | tail -n 1; }
set_json() { zk "set $1 $2" >/dev/null; }
set_assignment() {
  set_json "$1" "{\"partitionId\":\"$2\",\"epoch\":$3,\"primary\":\"$4\",\"replica\":\"$5\",\"state\":\"READY\"}"
}
restore() {
  if [[ "${RESTORE}" == true ]]; then
    # Restore the original topology but advance epochs; fencing epochs must
    # never move backwards, including after a benchmark failure.
    set_json "${P027}" "${RESTORE_P027}" || true
    set_json "${P132}" "${RESTORE_P132}" || true
  fi
}
trap restore EXIT

for container in dc-saas-cluster-zookeeper dc-saas-cluster-ordersvr-a dc-saas-cluster-ordersvr-b dc-saas-cluster-gateway; do
  [[ "$(sudo docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null || true)" == true ]] || die "${container} is not running"
done
command -v python3 >/dev/null || die 'python3 is required'
[[ -f "${LOAD_SCRIPT}" ]] || die "missing load generator: ${LOAD_SCRIPT}"
[[ "${REQUESTS}" =~ ^[1-9][0-9]*$ && "${CONCURRENCY}" =~ ^[1-9][0-9]*$ && "${WARMUP}" =~ ^[0-9]+$ ]] || die 'invalid load bounds'

ORIGINAL_P027="$(read_assignment "${P027}")"
ORIGINAL_P132="$(read_assignment "${P132}")"
[[ -n "${ORIGINAL_P027}" && -n "${ORIGINAL_P132}" ]] || die 'failed to read original assignments'
ORIGINAL_MAX_EPOCH="$(python3 -c 'import json,sys; print(max(json.loads(sys.argv[1])["epoch"],json.loads(sys.argv[2])["epoch"]))' "${ORIGINAL_P027}" "${ORIGINAL_P132}")"
if (( BASE_EPOCH <= ORIGINAL_MAX_EPOCH )); then BASE_EPOCH="$((ORIGINAL_MAX_EPOCH + 100))"; fi
RESTORE_P027="$(python3 -c 'import json,sys; value=json.loads(sys.argv[1]); value["epoch"]=int(sys.argv[2]); print(json.dumps(value,separators=(",",":")))' "${ORIGINAL_P027}" "$((BASE_EPOCH + 100))")"
RESTORE_P132="$(python3 -c 'import json,sys; value=json.loads(sys.argv[1]); value["epoch"]=int(sys.argv[2]); print(json.dumps(value,separators=(",",":")))' "${ORIGINAL_P132}" "$((BASE_EPOCH + 101))")"
RESTORE=true
sudo install -d -m 0750 "${EVIDENCE}"

run_load() {
  local mode="$1" iteration="$2" epoch="$3"
  if [[ "${mode}" == single-primary ]]; then
    set_assignment "${P027}" P027 "${epoch}" OrderSvrA OrderSvrB
    set_assignment "${P132}" P132 "$((epoch + 1))" OrderSvrA OrderSvrB
  else
    set_assignment "${P027}" P027 "${epoch}" OrderSvrA OrderSvrB
    set_assignment "${P132}" P132 "$((epoch + 1))" OrderSvrB OrderSvrA
  fi
  wait_route() {
    local symbol="$1" deadline=$((SECONDS + 60)) response probe_id
    probe_id="ROUTE-${RUN_ID}-${mode}-${iteration}-${symbol}"
    while (( SECONDS < deadline )); do
      response="$(curl -sS --max-time 10 -H 'Content-Type: application/json' \
        --data-binary "{\"serverName\":\"OrderSvr\",\"method\":\"__cluster_perf_probe__\",\"key\":\"WEB_E2E\\u001f4\\u001f${symbol}\",\"content\":{\"ClOrdID\":\"${probe_id}\",\"Location\":\"WEB_E2E\",\"MarketIndicator\":\"4\",\"SecurityID\":\"${symbol}\"}}" \
        "http://${GW_HOST}:${GW_PORT}" || true)"
      if [[ "${response}" == *'"code":0'* ]]; then return 0; fi
      sleep 1
    done
    die "${mode}/${iteration}: route ${symbol} did not become ready; last response=${response}"
  }
  wait_route BTCUSDT
  wait_route ETHUSDT
  local load_id="PERF-${RUN_ID}-${mode}-${iteration}"
  local output="${EVIDENCE}/${mode}-${iteration}.json"
  log "Running ${mode} iteration ${iteration}"
  python3 "${LOAD_SCRIPT}" --host "${GW_HOST}" --port "${GW_PORT}" --requests "${REQUESTS}" \
    --concurrency "${CONCURRENCY}" --warmup "${WARMUP}" --run-id "${load_id}" --mode "${mode}" --output "${output}"
  sleep 2
  local recorded
  recorded="$(( $(sudo grep -F -c "eventId:MEASURE-${load_id}" "${LOG_A}" || true) + $(sudo grep -F -c "eventId:MEASURE-${load_id}" "${LOG_B}" || true) ))"
  [[ "${recorded}" -eq "${REQUESTS}" ]] || die "${mode}/${iteration}: expected ${REQUESTS} recorded commands, found ${recorded}"
}

# A second run can use BAAB to counterbalance warm-JVM and host-load drift.
case "${SEQUENCE}" in
  ABBA)
    run_load single-primary 1 "${BASE_EPOCH}"
    run_load split-primary 1 "$((BASE_EPOCH + 10))"
    run_load split-primary 2 "$((BASE_EPOCH + 20))"
    run_load single-primary 2 "$((BASE_EPOCH + 30))"
    ;;
  BAAB)
    run_load split-primary 1 "${BASE_EPOCH}"
    run_load single-primary 1 "$((BASE_EPOCH + 10))"
    run_load single-primary 2 "$((BASE_EPOCH + 20))"
    run_load split-primary 2 "$((BASE_EPOCH + 30))"
    ;;
  *) die 'ORDER_CLUSTER_PERF_SEQUENCE must be ABBA or BAAB' ;;
esac

python3 - "${EVIDENCE}" "${RUN_ID}" "${STARTED_AT}" "${REQUESTS}" "${CONCURRENCY}" "${SEQUENCE}" <<'PY'
import json, os, statistics, sys
root, run_id, started_at, requests, concurrency, sequence = sys.argv[1:]
def load(mode):
    result = []
    for index in (1, 2):
        with open(os.path.join(root, "%s-%d.json" % (mode, index)), encoding="utf-8") as source:
            result.append(json.load(source))
    return result
baseline, split = load("single-primary"), load("split-primary")
baseline_tps = statistics.median(item["tps"] for item in baseline)
split_tps = statistics.median(item["tps"] for item in split)
change = (split_tps / baseline_tps - 1.0) * 100.0
report = {
  "result": "PASS", "scope": "gw-routing-order-shadow-journal-synchronous-replication",
  "businessOrderAcceptance": "NOT_TESTED", "runId": run_id, "startedAtUtc": started_at,
  "requestsPerRun": int(requests), "concurrency": int(concurrency),
  "method": "two-run median on the same host", "sequence": sequence,
  "singlePrimary": {"medianTps": baseline_tps, "runs": baseline},
  "splitPrimary": {"medianTps": split_tps, "runs": split},
  "tpsChangePercent": change,
  "verdict": "INCREASED" if change > 3.0 else ("DECREASED" if change < -3.0 else "FLAT")
}
with open(os.path.join(root, "result.json"), "w", encoding="utf-8") as target:
    json.dump(report, target, ensure_ascii=False, indent=2); target.write("\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
PY

restore
RESTORE=false
log "PASS: evidence=${EVIDENCE}/result.json"
