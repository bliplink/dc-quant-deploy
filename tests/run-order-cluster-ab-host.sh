#!/usr/bin/env bash
set -euo pipefail

ORDER_CLUSTER_DEV_ROOT="${ORDER_CLUSTER_DEV_ROOT:-/data/dc-saas-order-cluster-dev}"
GW_URL="${ORDER_CLUSTER_GW_URL:-http://127.0.0.1:33302}"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EVIDENCE_DIR="${ORDER_CLUSTER_DEV_ROOT}/evidence/${RUN_ID}"
GW_LOG="${ORDER_CLUSTER_DEV_ROOT}/log/GW.log"
ORDER_A_LOG="${ORDER_CLUSTER_DEV_ROOT}/log/OrderSvrA.log"
ORDER_B_LOG="${ORDER_CLUSTER_DEV_ROOT}/log/OrderSvrB.log"

log() { printf '[order-cluster-host] %s\n' "$*"; }
die() { printf '[order-cluster-host] ERROR: %s\n' "$*" >&2; exit 1; }

for container in dc-saas-cluster-zookeeper dc-saas-cluster-ordersvr-a dc-saas-cluster-ordersvr-b dc-saas-cluster-gateway; do
  [[ "$(sudo docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null || true)" == true ]] || die "${container} is not running"
done
sudo install -d -m 0750 "${EVIDENCE_DIR}"
for log_file in "${GW_LOG}" "${ORDER_A_LOG}" "${ORDER_B_LOG}"; do
  sudo test -f "${log_file}" || die "expected service log is missing: ${log_file}"
done
GW_START_LINE="$(( $(sudo wc -l "${GW_LOG}" | awk '{print $1}') + 1 ))"
ORDER_A_START_LINE="$(( $(sudo wc -l "${ORDER_A_LOG}" | awk '{print $1}') + 1 ))"
ORDER_B_START_LINE="$(( $(sudo wc -l "${ORDER_B_LOG}" | awk '{print $1}') + 1 ))"

request() {
  local name="$1" payload="$2"
  printf '%s\n' "${payload}" | sudo tee "${EVIDENCE_DIR}/${name}.request.json" >/dev/null
  sudo curl --silent --show-error --max-time 15 -H 'Content-Type: application/json' \
    --data-binary "@${EVIDENCE_DIR}/${name}.request.json" "${GW_URL}" |
    sudo tee "${EVIDENCE_DIR}/${name}.response.json" >/dev/null
}

wait_gateway_node() {
  local port="$1" node="$2" deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    if sudo tail -n "+${GW_START_LINE}" "${GW_LOG}" |
      grep -q "GwClient connected to Host:127.0.0.1,Port:${port}"; then
      return 0
    fi
    sleep 1
  done
  die "GW did not connect to ${node} on port ${port}"
}

log 'Triggering physical node connections through logical OrderSvr partition routing'
request probe-btc '{"serverName":"OrderSvr","method":"__cluster_route_readiness__","content":{"Location":"WEB_E2E","MarketIndicator":"4","SecurityID":"BTCUSDT"}}' || true
wait_gateway_node 33336 OrderSvrA
request probe-eth '{"serverName":"OrderSvr","method":"__cluster_route_readiness__","content":{"Location":"WEB_E2E","MarketIndicator":"4","SecurityID":"ETHUSDT"}}' || true
wait_gateway_node 33337 OrderSvrB

btc_clid="HOST-AB-BTC-${RUN_ID}"
eth_clid="HOST-AB-ETH-${RUN_ID}"
request order-btc "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"CLOSE\",\"OrderQty\":\"0.001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${btc_clid}\",\"Terminal\":\"ClusterE2E\",\"CloseBy\":\"liq\",\"Side\":\"Buy\",\"Price\":\"100\",\"UserID\":\"cluster-e2e\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"BTCUSDT\",\"Location\":\"WEB_E2E\",\"ReduceOnly\":\"true\"}}"
request order-eth "{\"serverName\":\"OrderSvr\",\"method\":\"placeOrder\",\"content\":{\"OCType\":\"CLOSE\",\"OrderQty\":\"0.001\",\"OrdType\":\"Limit\",\"ClOrdID\":\"${eth_clid}\",\"Terminal\":\"ClusterE2E\",\"CloseBy\":\"liq\",\"Side\":\"Buy\",\"Price\":\"100\",\"UserID\":\"cluster-e2e\",\"MarketIndicator\":\"4\",\"TimeInForce\":\"GTC\",\"SecurityID\":\"ETHUSDT\",\"Location\":\"WEB_E2E\",\"ReduceOnly\":\"true\"}}"

sleep 2
sudo tail -n "+${GW_START_LINE}" "${GW_LOG}" >"/tmp/order-cluster-gw-${RUN_ID}.log"
sudo tail -n "+${ORDER_A_START_LINE}" "${ORDER_A_LOG}" >"/tmp/order-cluster-a-${RUN_ID}.log"
sudo tail -n "+${ORDER_B_START_LINE}" "${ORDER_B_LOG}" >"/tmp/order-cluster-b-${RUN_ID}.log"
sudo install -m 0640 "/tmp/order-cluster-gw-${RUN_ID}.log" "${EVIDENCE_DIR}/gateway.log"
sudo install -m 0640 "/tmp/order-cluster-a-${RUN_ID}.log" "${EVIDENCE_DIR}/ordersvr-a.log"
sudo install -m 0640 "/tmp/order-cluster-b-${RUN_ID}.log" "${EVIDENCE_DIR}/ordersvr-b.log"
rm -f "/tmp/order-cluster-gw-${RUN_ID}.log" "/tmp/order-cluster-a-${RUN_ID}.log" "/tmp/order-cluster-b-${RUN_ID}.log"

sudo grep -Eq "ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvrA, partition:P027.*eventId:${btc_clid}.*replicaStatus:OK" "${EVIDENCE_DIR}/ordersvr-a.log" ||
  die 'BTCUSDT did not route to OrderSvrA with synchronous replica ACK'
sudo grep -Eq "ORDER_CLUSTER_COMMAND_RECORDED node:OrderSvrB, partition:P132.*eventId:${eth_clid}.*replicaStatus:OK" "${EVIDENCE_DIR}/ordersvr-b.log" ||
  die 'ETHUSDT did not route to OrderSvrB with synchronous replica ACK'
sudo grep -q 'Cluster.Zookeeper.Hosts=127.0.0.1:32182' "${EVIDENCE_DIR}/gateway.log" ||
  die 'GW did not use the isolated cluster development ZooKeeper'
if sudo grep -q 'Port:33036' "${EVIDENCE_DIR}/gateway.log"; then
  die 'GW connected to the existing production OrderSvr port'
fi
if sudo grep -Eq 'REPLICATION_(FAILED|TIMEOUT)|replicaStatus:(FAILED|TIMEOUT)' "${EVIDENCE_DIR}/ordersvr-a.log" "${EVIDENCE_DIR}/ordersvr-b.log"; then
  die 'replication failure appeared in OrderSvr logs'
fi
for config_file in \
  "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrA/application.properties" \
  "${ORDER_CLUSTER_DEV_ROOT}/nodes/OrderSvrB/application.properties"; do
  sudo grep -qx 'order.tenantSymbolRules.enabled=false' "${config_file}" ||
    die "tenant symbol rule database refresh is not disabled in ${config_file}"
done
if sudo grep -q 'Failed to refresh tenant symbol rules' \
  "${EVIDENCE_DIR}/ordersvr-a.log" "${EVIDENCE_DIR}/ordersvr-b.log"; then
  die 'tenant symbol rule database refresh failure appeared in current-run logs'
fi

order_image="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-ordersvr-a)"
gw_image="$(sudo docker inspect -f '{{.Config.Image}}' dc-saas-cluster-gateway)"
cat <<EOF | sudo tee "${EVIDENCE_DIR}/result.json" >/dev/null
{
  "result": "PASS",
  "scope": "partition-routing-and-shadow-command-replication",
  "businessOrderAcceptance": "NOT_TESTED",
  "businessOrderExclusion": "isolated stack intentionally has no LoginSvr, AdminSvr, TradeSvr, funds or market data",
  "runId": "${RUN_ID}",
  "startedAtUtc": "${STARTED_AT}",
  "orderImage": "${order_image}",
  "gwImage": "${gw_image}",
  "logicalService": "OrderSvr",
  "registryEndpoint": "127.0.0.1:32182",
  "tenantSymbolRuleDatabaseRefresh": "DISABLED",
  "productionOrderPortObserved": false,
  "routes": [
    {"key":"WEB_E2E/4/BTCUSDT","partition":"P027","primary":"OrderSvrA","replica":"OrderSvrB","replicaStatus":"OK"},
    {"key":"WEB_E2E/4/ETHUSDT","partition":"P132","primary":"OrderSvrB","replica":"OrderSvrA","replicaStatus":"OK"}
  ]
}
EOF

log "PASS: evidence=${EVIDENCE_DIR}/result.json"
