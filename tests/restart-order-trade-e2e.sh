#!/usr/bin/env bash

# Shared by host-side acceptance scripts after they replace isolated MySQL
# fixtures. The caller provides log, die and wait_for_port functions.
restart_order_trade_for_e2e() {
  if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
    local recovery_script="${SCRIPT_DIR}/recover-order-cluster-partitions-host.sh"
    [[ -x "${recovery_script}" ]] ||
      die "Missing executable cluster recovery script: ${recovery_script}"
    log "Keeping GW online while clustered OrderSvr A/B and TradeSvr restart."
    log "Restarting clustered OrderSvr A/B and TradeSvr on the clean E2E baseline."
    docker restart dc-saas-ordersvr dc-saas-ordersvr-b dc-saas-tradesvr >/dev/null
    wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
    wait_for_port "${ORDERSVR_B_GW_PORT}" dc-saas-ordersvr-b
    wait_for_port "${ORDERSVR_A_REPLICATION_PORT}" dc-saas-ordersvr
    wait_for_port "${ORDERSVR_B_REPLICATION_PORT}" dc-saas-ordersvr-b
    ORDER_CLUSTER_ZK_SERVER="127.0.0.1:${ZOOKEEPER_PORT}" "${recovery_script}"
  else
    log "Restarting OrderSvr and TradeSvr on the clean E2E baseline."
    docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
    wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
  fi
  wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
}
