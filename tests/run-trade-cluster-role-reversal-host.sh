#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
PARTITION_ROOT="${TRADE_CLUSTER_PARTITION_ROOT:-/dc/cluster/tradesvr/partitions}"
PARTITION_ID="${TRADE_CLUSTER_ROLE_REVERSAL_PARTITION:-P000}"
ZK_CONTAINER="${TRADE_CLUSTER_ZK_CONTAINER:-dc-saas-zookeeper}"
ZK_SERVER="${TRADE_CLUSTER_ZK_SERVER:-127.0.0.1:${ZOOKEEPER_PORT:-32181}}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"

log() { printf '[trade-cluster-role-reversal] %s\n' "$*"; }
die() { printf '[trade-cluster-role-reversal] ERROR: %s\n' "$*" >&2; exit 1; }
wait_for_port() { :; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

[[ "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]] ||
  die "TRADE_CLUSTER_ENABLED=true is required"
[[ "${PARTITION_ID}" =~ ^P[0-9]{3}$ ]] || die "Invalid partition id: ${PARTITION_ID}"

for container in dc-saas-zookeeper dc-saas-mysql dc-saas-tradesvr dc-saas-tradesvr-b dc-saas-projectionsvr; do
  [[ "$(docker inspect --format '{{.State.Running}}' "${container}" 2>/dev/null || true)" == "true" ]] ||
    die "Required container is not running: ${container}"
done

EVIDENCE_ROOT="${TRADE_CLUSTER_EVIDENCE_ROOT:-${DEPLOY_ROOT}/evidence}"
EVIDENCE_DIR="${EVIDENCE_ROOT}/${RUN_ID}-trade-role-reversal"
install -d -m 0750 "${EVIDENCE_DIR}"
PLAN_FORWARD="${EVIDENCE_DIR}/forward.json"
PLAN_RETURN="${EVIDENCE_DIR}/return.json"
PROJECTION_BEFORE="${EVIDENCE_DIR}/projection-before.tsv"
PROJECTION_AFTER="${EVIDENCE_DIR}/projection-after.tsv"

# Reuse the same all-partition durable watermark checks used by restart acceptance.
# shellcheck disable=SC1090
source "${SCRIPT_DIR}/restart-order-trade-e2e.sh"

read_current_primary() {
  PYTHONPATH="${DEPLOY_DIR}" python3 - "${ZK_CONTAINER}" "${ZK_SERVER}" "${PARTITION_ROOT}" "${PARTITION_ID}" <<'PY'
import sys
from tests.md_cluster_transition_host import DockerZk

container, server, root, partition = sys.argv[1:]
row = DockerZk(container, server, root, "docker").read(partition)["value"]
primary = row.get("primary")
replicas = row.get("replicas") or [row.get("replica")]
replicas = [str(x).strip() for x in replicas if x and str(x).strip()]
if primary not in ("TradeSvrA", "TradeSvrB") or len(replicas) != 1:
    raise SystemExit("invalid Trade topology: %r" % row)
print(primary, replicas[0])
PY
}

switch_and_verify() {
  local source="$1" target="$2" target_container="$3" plan="$4"
  log "Switching ${PARTITION_ID}: ${source} -> ${target}"
  python3 "${SCRIPT_DIR}/trade_cluster_transition_host.py"     --zk-container "${ZK_CONTAINER}"     --zk-server "${ZK_SERVER}"     --partition-root "${PARTITION_ROOT}"     switch-primary     --from-node "${source}"     --to-node "${target}"     --partition "${PARTITION_ID}"     --limit 1     --batch-size 1     --plan "${plan}"     --apply     --confirm-root "${PARTITION_ROOT}"

  python3 "${SCRIPT_DIR}/trade_cluster_transition_host.py"     --zk-container "${ZK_CONTAINER}"     --zk-server "${ZK_SERVER}"     --partition-root "${PARTITION_ROOT}"     verify-ready     --plan "${plan}"     --target-node "${target}"     --target-container "${target_container}"
}

read -r original_primary original_replica < <(read_current_primary)
[[ "${original_primary}" != "${original_replica}" ]] || die "Primary and replica overlap"

if [[ "${original_primary}" == "TradeSvrA" ]]; then
  forward_container="dc-saas-tradesvr-b"
  return_container="dc-saas-tradesvr"
else
  forward_container="dc-saas-tradesvr"
  return_container="dc-saas-tradesvr-b"
fi

log "Capturing ProjectionSvr watermarks before role reversal."
snapshot_projection_watermarks "${PROJECTION_BEFORE}"

switch_and_verify "${original_primary}" "${original_replica}" "${forward_container}" "${PLAN_FORWARD}"
switch_and_verify "${original_replica}" "${original_primary}" "${return_container}" "${PLAN_RETURN}"

log "Verifying ProjectionSvr watermarks after both promotion barriers."
verify_projection_watermarks_not_regressed "${PROJECTION_BEFORE}"
snapshot_projection_watermarks "${PROJECTION_AFTER}"

read -r final_primary final_replica < <(read_current_primary)
[[ "${final_primary}" == "${original_primary}" && "${final_replica}" == "${original_replica}" ]] ||
  die "Final topology was not restored: primary=${final_primary}, replica=${final_replica}"

python3 - "${EVIDENCE_DIR}/summary.json" "${PARTITION_ID}" "${original_primary}" "${original_replica}" <<'PY'
import json
import sys
path, partition, primary, replica = sys.argv[1:]
with open(path, "w", encoding="utf-8") as stream:
    json.dump({
        "status": "PASS",
        "scope": "trade-cluster-role-reversal",
        "partitionId": partition,
        "originalPrimary": primary,
        "originalReplica": replica,
        "forwardReadiness": "PASS",
        "returnReadiness": "PASS",
        "projectionWatermarkContinuity": "PASS",
        "finalTopologyRestored": True,
    }, stream, indent=2, sort_keys=True)
    stream.write("\n")
PY

log "PASS evidence=${EVIDENCE_DIR}"
