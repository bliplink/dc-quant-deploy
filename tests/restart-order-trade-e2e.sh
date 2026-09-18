#!/usr/bin/env bash

# Shared by host-side acceptance scripts after they replace isolated MySQL
# fixtures. The caller provides log, die and wait_for_port functions.

snapshot_projection_watermarks() {
  local output="$1"
  : >"${output}"
  if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
    docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
      mysql -u"${MYSQL_USERNAME}" -N -B dc -e \
      "SELECT 'ORDER',partition_id,source_epoch,journal_seq FROM dc_order_projection_watermark ORDER BY partition_id" \
      >>"${output}"
  fi
  if [[ "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
    docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql \
      mysql -u"${MYSQL_USERNAME}" -N -B dc -e \
      "SELECT 'TRADE',partition_id,source_epoch,journal_seq FROM dc_trade_projection_watermark ORDER BY partition_id" \
      >>"${output}"
  fi
}

verify_projection_watermarks_not_regressed() {
  local before="$1" after
  after="$(mktemp)"
  snapshot_projection_watermarks "${after}"
  python3 - "${before}" "${after}" <<'PY'
import sys

def load(path):
    rows = {}
    with open(path, encoding="utf-8") as stream:
        for raw in stream:
            parts = raw.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            stream_type, partition_id, epoch, seq = parts
            rows[(stream_type, partition_id)] = (int(epoch), int(seq))
    return rows

before = load(sys.argv[1])
after = load(sys.argv[2])
missing = []
regressed = []
for key, old in sorted(before.items()):
    current = after.get(key)
    if current is None:
        missing.append("%s/%s" % key)
    elif current < old:
        regressed.append("%s/%s %s -> %s" % (key[0], key[1], old, current))
if missing or regressed:
    if missing:
        print("missing projection watermark rows: " + ", ".join(missing), file=sys.stderr)
    if regressed:
        print("regressed projection watermarks: " + "; ".join(regressed), file=sys.stderr)
    raise SystemExit(1)
print("projection watermark continuity PASS (%d baseline rows)" % len(before))
PY
  local status=$?
  rm -f "${after}"
  return "${status}"
}

restart_order_trade_for_e2e() {
  local robot_was_running=false
  local restart_status=0
  local projection_before=""
  if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" || "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
    projection_before="$(mktemp)"
    log "Capturing durable ProjectionSvr watermarks before the Order/Trade recovery boundary."
    snapshot_projection_watermarks "${projection_before}"
  fi
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
      log "Keeping GW online while the recovery script fences, restarts and restores clustered OrderSvr A/B."
      ORDER_CLUSTER_ZK_SERVER="127.0.0.1:${ZOOKEEPER_PORT}" \
        ORDER_CLUSTER_RESTART_AFTER_FENCE=true \
        ORDER_CLUSTER_A_GW_PORT="${ORDERSVR_GW_PORT}" \
        ORDER_CLUSTER_B_GW_PORT="${ORDERSVR_B_GW_PORT}" \
        ORDER_CLUSTER_A_REPLICATION_PORT="${ORDERSVR_A_REPLICATION_PORT}" \
        ORDER_CLUSTER_B_REPLICATION_PORT="${ORDERSVR_B_REPLICATION_PORT}" \
        ORDER_CLUSTER_TRADE_GW_PORT="${TRADESVR_GW_PORT}" \
        "${recovery_script}"
    else
      log "Restarting OrderSvr and TradeSvr on the clean E2E baseline."
      docker restart dc-saas-ordersvr dc-saas-tradesvr >/dev/null
      wait_for_port "${ORDERSVR_GW_PORT}" dc-saas-ordersvr
    fi
    wait_for_port "${TRADESVR_GW_PORT}" dc-saas-tradesvr
  ) || restart_status=$?

  if (( restart_status == 0 )) && [[ -n "${projection_before}" ]]; then
    log "Verifying ProjectionSvr durable watermarks did not disappear or move backward."
    verify_projection_watermarks_not_regressed "${projection_before}" || restart_status=$?
  fi
  [[ -z "${projection_before}" ]] || rm -f "${projection_before}"

  if [[ "${robot_was_running}" == "true" ]]; then
    log "Restoring RobotSvr after the OrderSvr recovery boundary."
    docker start dc-saas-robotsvr >/dev/null
  fi
  (( restart_status == 0 )) || return "${restart_status}"
}
