#!/usr/bin/env bash
set -euo pipefail

ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="${CHECKOUT}/compose.order-cluster-dev.yaml"
PROJECT="dc-saas-order-cluster-dev"
GW_URL="${ORDER_CLUSTER_GW_URL:-http://127.0.0.1:33302}"
ZK_CONTAINER="${ZOOKEEPER_CONTAINER:-dc-saas-cluster-zookeeper}"
ZK_ENDPOINT="${ZOOKEEPER_ENDPOINT:-127.0.0.1:32182}"
PARTITION_PATH="/dc/cluster/ordersvr-dev/partitions/P027"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EVIDENCE="${ROOT}/evidence/${RUN_ID}-node-failure-recovery"
LOG_A="${ROOT}/log/OrderSvrA.log"
LOG_B="${ROOT}/log/OrderSvrB.log"
NODE_A="dc-saas-cluster-ordersvr-a"
NODE_B="dc-saas-cluster-ordersvr-b"
NODE_A_STOPPED=false
ASSIGNMENT_CHANGED=false

log() { printf '[order-cluster-failure-recovery] %s\n' "$*"; }
die() { printf '[order-cluster-failure-recovery] ERROR: %s\n' "$*" >&2; exit 1; }
zk() { printf '%s\nquit\n' "$1" | sudo docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_ENDPOINT}" 2>/dev/null; }
read_assignment() { zk "get ${PARTITION_PATH}" | grep -E '^\{"partitionId"' | tail -n 1; }
set_assignment() {
  local epoch="$1" primary="$2" replica="$3"
  zk "set ${PARTITION_PATH} {\"partitionId\":\"P027\",\"epoch\":${epoch},\"primary\":\"${primary}\",\"replica\":\"${replica}\",\"state\":\"READY\"}" >/dev/null
}

start_node_a() {
  export ORDER_CLUSTER_DEV_ROOT="${ROOT}"
  export ORDERSVR_CLUSTER_DEV_IMAGE GW_CLUSTER_DEV_IMAGE
  sudo -E docker compose -p "${PROJECT}" -f "${COMPOSE}" up -d ordersvr-a >/dev/null
  NODE_A_STOPPED=false
}

wait_healthy() {
  local container="$1" deadline=$((SECONDS + 120)) status
  while (( SECONDS < deadline )); do
    status="$(sudo docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${container}" 2>/dev/null || true)"
    [[ "${status}" == healthy ]] && return 0
    [[ "${status}" == unhealthy ]] && die "${container} became unhealthy"
    sleep 2
  done
  die "${container} did not become healthy"
}

wait_log() {
  local file="$1" pattern="$2" deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    sudo grep -Eq "${pattern}" "${file}" && return 0
    sleep 1
  done
  die "log condition did not appear: ${pattern}"
}

probe() {
  local event_id="$1"
  sudo curl --silent --show-error --max-time 15 -H 'Content-Type: application/json' \
    --data-binary "{\"serverName\":\"OrderSvr\",\"method\":\"__cluster_perf_probe__\",\"key\":\"WEB_E2E\\u001f4\\u001fBTCUSDT\",\"content\":{\"ClOrdID\":\"${event_id}\",\"Location\":\"WEB_E2E\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\"}}" \
    "${GW_URL}" || true
}

wait_ready_probe() {
  local event_id="$1" target="$2" epoch="$3" deadline=$((SECONDS + 120)) response
  while (( SECONDS < deadline )); do
    response="$(probe "${event_id}")"
    if [[ "${response}" == *'"code":0'* ]]; then
      printf '%s\n' "${response}" | sudo tee "${EVIDENCE}/${event_id}.response.json" >/dev/null
      wait_log "${target}" "ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvr[AB], partition:P027, epoch:${epoch}.*eventId:${event_id}.*replicaStatus:OK"
      return 0
    fi
    sleep 1
  done
  die "partition did not become ready at epoch ${epoch}; last response=${response:-empty}"
}

restore() {
  if [[ "${NODE_A_STOPPED}" == true ]]; then start_node_a || true; fi
  if [[ "${ASSIGNMENT_CHANGED}" == true ]]; then set_assignment "${RESTORE_EPOCH}" OrderSvrA OrderSvrB || true; fi
}
trap restore EXIT

for container in "${ZK_CONTAINER}" "${NODE_A}" "${NODE_B}" dc-saas-cluster-gateway; do
  [[ "$(sudo docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null || true)" == true ]] || die "${container} is not running"
done
command -v python3 >/dev/null || die 'python3 is required'
sudo install -d -m 0750 "${EVIDENCE}"

ORDERSVR_CLUSTER_DEV_IMAGE="$(sudo docker inspect -f '{{.Config.Image}}' "${NODE_A}")"
GW_CLUSTER_DEV_IMAGE="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-gateway)"
ORIGINAL="$(read_assignment)"
[[ -n "${ORIGINAL}" ]] || die 'P027 assignment is missing'
ORIGINAL_EPOCH="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["epoch"])' "${ORIGINAL}")"
BASE_EPOCH="$(date +%s%N | cut -c1-15)"
if (( BASE_EPOCH <= ORIGINAL_EPOCH )); then BASE_EPOCH="$((ORIGINAL_EPOCH + 100))"; fi
B_EPOCH="${BASE_EPOCH}"
A_EPOCH="$((BASE_EPOCH + 1))"
RESTORE_EPOCH="$((BASE_EPOCH + 2))"

A_START="$(( $(sudo wc -l "${LOG_A}" | awk '{print $1}') + 1 ))"
B_START="$(( $(sudo wc -l "${LOG_B}" | awk '{print $1}') + 1 ))"

log 'Stopping the isolated current primary OrderSvrA'
sudo docker stop "${NODE_A}" >/dev/null
NODE_A_STOPPED=true
set_assignment "${B_EPOCH}" OrderSvrB OrderSvrA
ASSIGNMENT_CHANGED=true

wait_log "${LOG_B}" "ORDER_PARTITION_RECOVERY_FAILED node:OrderSvrB, partition:P027, epoch:${B_EPOCH}"
BLOCKED_RESPONSE="$(probe "FAIL-CLOSED-${RUN_ID}")"
printf '%s\n' "${BLOCKED_RESPONSE}" | sudo tee "${EVIDENCE}/fail-closed.response.json" >/dev/null
[[ "${BLOCKED_RESPONSE}" != *'"code":0'* ]] || die 'partition accepted traffic without a live replica during required promotion barrier'

log 'Restarting OrderSvrA and waiting for snapshot rebase before OrderSvrB readiness opens'
start_node_a
wait_healthy "${NODE_A}"
wait_ready_probe "RECOVER-B-${RUN_ID}" "${LOG_B}" "${B_EPOCH}"
wait_log "${LOG_B}" "ORDER_PARTITION_PROMOTION_READY node:OrderSvrB, partition:P027, epoch:${B_EPOCH}"

log 'Returning P027 to OrderSvrA through another recovery barrier'
set_assignment "${A_EPOCH}" OrderSvrA OrderSvrB
wait_ready_probe "RECOVER-A-${RUN_ID}" "${LOG_A}" "${A_EPOCH}"
wait_log "${LOG_A}" "ORDER_PARTITION_PROMOTION_READY node:OrderSvrA, partition:P027, epoch:${A_EPOCH}"
ASSIGNMENT_CHANGED=false

sudo tail -n "+${A_START}" "${LOG_A}" | sudo tee "${EVIDENCE}/ordersvr-a.log" >/dev/null
sudo tail -n "+${B_START}" "${LOG_B}" | sudo tee "${EVIDENCE}/ordersvr-b.log" >/dev/null
cat <<EOF | sudo tee "${EVIDENCE}/result.json" >/dev/null
{
  "result": "PASS",
  "scope": "isolated-primary-process-failure-recovery",
  "runId": "${RUN_ID}",
  "startedAtUtc": "${STARTED_AT}",
  "orderImage": "${ORDERSVR_CLUSTER_DEV_IMAGE}",
  "gwImage": "${GW_CLUSTER_DEV_IMAGE}",
  "failedNode": "OrderSvrA",
  "failureMode": "FAIL_CLOSED_UNTIL_REQUIRED_REPLICA_REJOINED",
  "rpoPolicy": "SYNCHRONOUS_REPLICA_REQUIRED",
  "transitions": [
    {"epoch":${B_EPOCH},"primary":"OrderSvrB","replica":"OrderSvrA","readinessAfterReplicaRejoin":"PASS"},
    {"epoch":${A_EPOCH},"primary":"OrderSvrA","replica":"OrderSvrB","readiness":"PASS"}
  ],
  "finalAssignment": {"epoch":${A_EPOCH},"primary":"OrderSvrA","replica":"OrderSvrB"}
}
EOF

trap - EXIT
log "PASS: evidence=${EVIDENCE}/result.json"
