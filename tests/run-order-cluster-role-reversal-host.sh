#!/usr/bin/env bash
set -euo pipefail

ORDER_CLUSTER_DEV_ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
GW_URL="${ORDER_CLUSTER_GW_URL:-http://127.0.0.1:33302}"
ZOOKEEPER_CONTAINER="${ZOOKEEPER_CONTAINER:-dc-saas-cluster-zookeeper}"
ZOOKEEPER_ENDPOINT="${ZOOKEEPER_ENDPOINT:-127.0.0.1:32182}"
PARTITION_PATH="/dc/cluster/ordersvr-dev/partitions/P027"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EVIDENCE_DIR="${ORDER_CLUSTER_DEV_ROOT}/evidence/${RUN_ID}-role-reversal"
GW_LOG="${ORDER_CLUSTER_DEV_ROOT}/log/GW.log"
ORDER_A_LOG="${ORDER_CLUSTER_DEV_ROOT}/log/OrderSvrA.log"
ORDER_B_LOG="${ORDER_CLUSTER_DEV_ROOT}/log/OrderSvrB.log"
BASE_EPOCH="$(date +%s%N | cut -c1-15)"
B_PRIMARY_EPOCH="${BASE_EPOCH}"
A_PRIMARY_EPOCH="$((BASE_EPOCH + 1))"
RESTORE_REQUIRED=false

log() { printf '[order-cluster-role-reversal] %s\n' "$*"; }
die() { printf '[order-cluster-role-reversal] ERROR: %s\n' "$*" >&2; exit 1; }

set_assignment() {
  local epoch="$1" primary="$2" replica="$3"
  printf 'set %s {"partitionId":"P027","epoch":%s,"primary":"%s","replica":"%s","state":"READY"}\nquit\n' \
    "${PARTITION_PATH}" "${epoch}" "${primary}" "${replica}" |
    sudo docker exec -i "${ZOOKEEPER_CONTAINER}" zkCli.sh -server "${ZOOKEEPER_ENDPOINT}" \
      >"/tmp/order-cluster-role-zk-${RUN_ID}.log" 2>&1
}

restore_primary() {
  if [[ "${RESTORE_REQUIRED}" == true ]]; then
    set_assignment "${A_PRIMARY_EPOCH}" OrderSvrA OrderSvrB || true
  fi
  rm -f "/tmp/order-cluster-role-zk-${RUN_ID}.log"
}
trap restore_primary EXIT

wait_ready_probe() {
  local name="$1" event_id="$2" deadline=$((SECONDS + 90)) response
  local payload="{\"serverName\":\"OrderSvr\",\"method\":\"__cluster_perf_probe__\",\"content\":{\"ClOrdID\":\"${event_id}\",\"Location\":\"WEB_E2E\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\"}}"
  printf '%s\n' "${payload}" | sudo tee "${EVIDENCE_DIR}/${name}.request.json" >/dev/null
  while (( SECONDS < deadline )); do
    response="$(sudo curl --silent --show-error --max-time 15 -H 'Content-Type: application/json' \
      --data-binary "@${EVIDENCE_DIR}/${name}.request.json" "${GW_URL}" || true)"
    if [[ "${response}" == *'"code":0'* ]]; then
      printf '%s\n' "${response}" | sudo tee "${EVIDENCE_DIR}/${name}.response.json" >/dev/null
      return 0
    fi
    sleep 1
  done
  printf '%s\n' "${response:-}" | sudo tee "${EVIDENCE_DIR}/${name}.response.json" >/dev/null
  die "${event_id} did not pass the partition readiness gate; last response=${response:-empty}"
}

wait_record() {
  local log_file="$1" node="$2" epoch="$3" event_id="$4" deadline=$((SECONDS + 30))
  while (( SECONDS < deadline )); do
    if sudo grep -Eq "ORDER_CLUSTER_COMMAND_RECORDED node:${node}, partition:P027, epoch:${epoch}.*eventId:${event_id}.*replicaStatus:OK" "${log_file}"; then
      return 0
    fi
    sleep 1
  done
  die "${event_id} was not recorded by ${node} with synchronous replica ACK"
}

archive_count() {
  local node="$1" path="${ORDER_CLUSTER_DEV_ROOT}/data/${node}/journal/.archive"
  if ! sudo test -d "${path}"; then
    printf '0\n'
    return
  fi
  sudo find "${path}" -mindepth 1 -maxdepth 1 -type d | sudo wc -l
}

for container in dc-saas-cluster-zookeeper dc-saas-cluster-ordersvr-a dc-saas-cluster-ordersvr-b dc-saas-cluster-gateway; do
  [[ "$(sudo docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null || true)" == true ]] ||
    die "${container} is not running"
done
sudo install -d -m 0750 "${EVIDENCE_DIR}"
for log_file in "${GW_LOG}" "${ORDER_A_LOG}" "${ORDER_B_LOG}"; do
  sudo test -f "${log_file}" || die "expected service log is missing: ${log_file}"
done
GW_START_LINE="$(( $(sudo wc -l "${GW_LOG}" | awk '{print $1}') + 1 ))"
ORDER_A_START_LINE="$(( $(sudo wc -l "${ORDER_A_LOG}" | awk '{print $1}') + 1 ))"
ORDER_B_START_LINE="$(( $(sudo wc -l "${ORDER_B_LOG}" | awk '{print $1}') + 1 ))"

B_EVENT_ID="ROLE-B-${RUN_ID}"
A_EVENT_ID="ROLE-A-${RUN_ID}"
A_ARCHIVES_BEFORE="$(archive_count OrderSvrA)"
B_ARCHIVES_BEFORE="$(archive_count OrderSvrB)"

log "Promoting OrderSvrB for P027 at epoch ${B_PRIMARY_EPOCH}"
RESTORE_REQUIRED=true
set_assignment "${B_PRIMARY_EPOCH}" OrderSvrB OrderSvrA
wait_ready_probe order-on-b "${B_EVENT_ID}"
wait_record "${ORDER_B_LOG}" OrderSvrB "${B_PRIMARY_EPOCH}" "${B_EVENT_ID}"

log "Returning P027 to OrderSvrA at epoch ${A_PRIMARY_EPOCH}"
set_assignment "${A_PRIMARY_EPOCH}" OrderSvrA OrderSvrB
wait_ready_probe order-on-a "${A_EVENT_ID}"
wait_record "${ORDER_A_LOG}" OrderSvrA "${A_PRIMARY_EPOCH}" "${A_EVENT_ID}"
RESTORE_REQUIRED=false

A_ARCHIVES_AFTER="$(archive_count OrderSvrA)"
B_ARCHIVES_AFTER="$(archive_count OrderSvrB)"
(( A_ARCHIVES_AFTER > A_ARCHIVES_BEFORE )) || die 'OrderSvrA did not archive its old-epoch journal during rebase'
(( B_ARCHIVES_AFTER > B_ARCHIVES_BEFORE )) || die 'OrderSvrB did not archive its old-epoch journal during rebase'

sudo tail -n "+${GW_START_LINE}" "${GW_LOG}" >"/tmp/order-cluster-role-gw-${RUN_ID}.log"
sudo tail -n "+${ORDER_A_START_LINE}" "${ORDER_A_LOG}" >"/tmp/order-cluster-role-a-${RUN_ID}.log"
sudo tail -n "+${ORDER_B_START_LINE}" "${ORDER_B_LOG}" >"/tmp/order-cluster-role-b-${RUN_ID}.log"
sudo install -m 0640 "/tmp/order-cluster-role-gw-${RUN_ID}.log" "${EVIDENCE_DIR}/gateway.log"
sudo install -m 0640 "/tmp/order-cluster-role-a-${RUN_ID}.log" "${EVIDENCE_DIR}/ordersvr-a.log"
sudo install -m 0640 "/tmp/order-cluster-role-b-${RUN_ID}.log" "${EVIDENCE_DIR}/ordersvr-b.log"
rm -f "/tmp/order-cluster-role-gw-${RUN_ID}.log" "/tmp/order-cluster-role-a-${RUN_ID}.log" "/tmp/order-cluster-role-b-${RUN_ID}.log"

if sudo grep -Eq 'REPLICATION_(FAILED|TIMEOUT)|replicaStatus:(FAILED|TIMEOUT)' \
  "${EVIDENCE_DIR}/ordersvr-a.log" "${EVIDENCE_DIR}/ordersvr-b.log"; then
  die 'replication failure appeared during role reversal'
fi
sudo grep -Eq "ORDER_PARTITION_PROMOTION_READY node:OrderSvrB, partition:P027, epoch:${B_PRIMARY_EPOCH}" \
  "${EVIDENCE_DIR}/ordersvr-b.log" || die 'OrderSvrB readiness did not follow recovery and promotion barrier'
sudo grep -Eq "ORDER_PARTITION_PROMOTION_READY node:OrderSvrA, partition:P027, epoch:${A_PRIMARY_EPOCH}" \
  "${EVIDENCE_DIR}/ordersvr-a.log" || die 'OrderSvrA readiness did not follow recovery and promotion barrier'
if sudo grep -q 'Port:33036' "${EVIDENCE_DIR}/gateway.log"; then
  die 'isolated GW connected to the existing production OrderSvr port'
fi

order_image="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-ordersvr-a)"
gw_image="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-gateway)"
cat <<EOF | sudo tee "${EVIDENCE_DIR}/result.json" >/dev/null
{
  "result": "PASS",
  "scope": "online-role-reversal-and-shadow-command-replication",
  "businessOrderAcceptance": "NOT_TESTED",
  "businessOrderExclusion": "isolated stack intentionally has no LoginSvr, AdminSvr, TradeSvr, funds or market data",
  "nodeFailure": "NOT_INJECTED",
  "runId": "${RUN_ID}",
  "startedAtUtc": "${STARTED_AT}",
  "orderImage": "${order_image}",
  "gwImage": "${gw_image}",
  "partition": "P027",
  "readinessFence": "PASS",
  "crossEpochSnapshotRebase": "PASS",
  "archiveCounts": {
    "OrderSvrA": {"before":${A_ARCHIVES_BEFORE},"after":${A_ARCHIVES_AFTER}},
    "OrderSvrB": {"before":${B_ARCHIVES_BEFORE},"after":${B_ARCHIVES_AFTER}}
  },
  "transitions": [
    {"epoch":${B_PRIMARY_EPOCH},"primary":"OrderSvrB","replica":"OrderSvrA","eventId":"${B_EVENT_ID}","replicaStatus":"OK"},
    {"epoch":${A_PRIMARY_EPOCH},"primary":"OrderSvrA","replica":"OrderSvrB","eventId":"${A_EVENT_ID}","replicaStatus":"OK"}
  ],
  "finalAssignment": {"primary":"OrderSvrA","replica":"OrderSvrB","epoch":${A_PRIMARY_EPOCH}}
}
EOF

rm -f "/tmp/order-cluster-role-zk-${RUN_ID}.log"
log "PASS: evidence=${EVIDENCE_DIR}/result.json"
