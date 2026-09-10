#!/usr/bin/env bash

# Shared by host-side acceptance scripts after they replace isolated MySQL
# fixtures. The caller provides log, die and wait_for_port functions.
restart_order_trade_for_e2e() {
  local robot_was_running=false
  local restart_status=0
  if [[ "$(docker inspect --format '{{.State.Running}}' dc-saas-robotsvr 2>/dev/null || true)" == "true" ]]; then
    robot_was_running=true
    log "Pausing RobotSvr before OrderSvr restart so no strategy write can cross the recovery boundary."
    docker stop dc-saas-robotsvr >/dev/null
  fi

  (
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
  ) || restart_status=$?

  if [[ "${robot_was_running}" == "true" ]]; then
    log "Restoring RobotSvr after the OrderSvr recovery boundary."
    docker start dc-saas-robotsvr >/dev/null
  fi
  (( restart_status == 0 )) || return "${restart_status}"
}
