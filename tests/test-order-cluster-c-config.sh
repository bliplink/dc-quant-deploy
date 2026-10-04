#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEST_ROOT="$(mktemp -d)"

cleanup() {
  [[ -n "${TEST_ROOT}" && -d "${TEST_ROOT}" ]] && rm -rf -- "${TEST_ROOT}"
}
trap cleanup EXIT

fail() {
  printf '[order-cluster-c-config-test] ERROR: %s\n' "$*" >&2
  exit 1
}

sed \
  -e "s|^DEPLOY_ROOT=.*|DEPLOY_ROOT=${TEST_ROOT}/runtime|" \
  -e 's|^ORDER_CLUSTER_ENABLED=.*|ORDER_CLUSTER_ENABLED=true|' \
  -e 's|^ORDER_CLUSTER_C_ENABLED=.*|ORDER_CLUSTER_C_ENABLED=true|' \
  -e 's|^ORDER_CLUSTER_FAILOVER_ENABLED=.*|ORDER_CLUSTER_FAILOVER_ENABLED=true|' \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/cluster.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/cluster.env" >/dev/null

ats="${TEST_ROOT}/runtime/control/ATSConfig.ini"
a_config="${TEST_ROOT}/runtime/control/overrides/OrderSvrA/config/application.properties"
b_config="${TEST_ROOT}/runtime/control/overrides/OrderSvrB/config/application.properties"
c_config="${TEST_ROOT}/runtime/control/overrides/OrderSvrC/config/application.properties"
peers='order.cluster.replication.peers=OrderSvrA=127.0.0.1:19121,OrderSvrB=127.0.0.1:19122,OrderSvrC=127.0.0.1:19123'

grep -Fqx 'SERVER.OrderSvrC.Name=OrderSvrC' "${ats}" || fail 'OrderSvrC server registration is missing'
grep -Fqx 'Partition.OrderSvrC.EnforceReadiness=true' "${ats}" || fail 'OrderSvrC readiness fence is missing'
grep -Fqx 'Partition.OrderSvr.PlacementEnabled=false' "${ats}" || fail 'logical Order placement must stay disabled'
grep -Fqx 'Partition.OrderSvrA.PlacementEnabled=false' "${ats}" || fail 'OrderSvrA placement must stay disabled'
grep -Fqx 'Partition.OrderSvrB.PlacementEnabled=false' "${ats}" || fail 'OrderSvrB placement must stay disabled'
grep -Fqx 'Partition.OrderSvrC.PlacementEnabled=false' "${ats}" || fail 'OrderSvrC placement must stay disabled'
grep -Fqx 'Partition.OrderSvr.PlacementPath=/dc/cluster/ordersvr/desired/placement' "${ats}" || fail 'Order placement path is missing'
grep -Fqx 'serverKey=SERVER.OrderSvrC' "${c_config}" || fail 'OrderSvrC physical identity is missing'
grep -Fqx 'orderStorePath=../../data/OrderSvrC/store' "${c_config}" || fail 'OrderSvrC data path is not isolated'
grep -Fqx 'order.cluster.replication.port=19123' "${c_config}" || fail 'OrderSvrC replication port is missing'
grep -Fqx 'order.cluster.snapshot.periodic.enabled=false' "${c_config}" || fail 'periodic snapshots must stay disabled by default'
for config in "${a_config}" "${b_config}" "${c_config}"; do
  grep -Fqx "${peers}" "${config}" || fail "three-node peer map is missing from ${config}"
done
for config in "${a_config}" "${b_config}" "${c_config}"; do
  grep -Fqx 'order.cluster.failover.enabled=true' "${config}" || fail "automatic failover is not enabled in ${config}"
  grep -Fqx 'order.cluster.failover.nodes=OrderSvrA,OrderSvrB,OrderSvrC' "${config}" || fail "failover node set is incomplete in ${config}"
  grep -Fqx 'order.cluster.failover.safetyPollMillis=1000' "${config}" || fail "failover safety poll is incorrect in ${config}"
  grep -Fqx 'order.cluster.failover.minimumLiveSynchronizedReplicas=2' "${config}" || fail "failover replica quorum is incorrect in ${config}"
  grep -Fqx 'order.cluster.failover.replicaRepairPollMillis=5000' "${config}" || fail "replica auto-repair poll is incorrect in ${config}"
done

[[ "$(grep -Fc 'DC_ZOOKEEPER_SESSION_TIMEOUT_MS: ${ORDERSVR_ZOOKEEPER_SESSION_TIMEOUT_MS:-6000}' "${DEPLOY_DIR}/compose.yaml")" -eq 3 ]] || fail 'all three Order nodes must request 6000ms ZooKeeper sessions'
[[ "$(grep -Fc 'DC_ZOOKEEPER_CONNECTION_TIMEOUT_MS: ${ORDERSVR_ZOOKEEPER_CONNECTION_TIMEOUT_MS:-5000}' "${DEPLOY_DIR}/compose.yaml")" -eq 3 ]] || fail 'all three Order nodes must request 5000ms ZooKeeper connections'
grep -Fq 'upsert_env_value ORDER_CLUSTER_FAILOVER_ENABLED true' "${DEPLOY_DIR}/deploy-saas.sh" || fail 'full-cluster profile does not enable Order failover'
grep -Fq 'upsert_env_value ORDERSVR_ZOOKEEPER_SESSION_TIMEOUT_MS 6000' "${DEPLOY_DIR}/deploy-saas.sh" || fail 'full-cluster profile does not pin Order ZooKeeper session timeout'
python3 - "${DEPLOY_DIR}/deploy-saas.sh" <<'PY2'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text()
block=s[s.index('ensure_order_cluster_assignments()'):s.index('ensure_trade_cluster_assignments()')]
for token in ('assignmentVersion', 'replicas', 'learners', 'OrderSvrC'):
    assert token in block, token
PY2

grep -Fqx '  ordersvr-c:' "${DEPLOY_DIR}/compose.yaml" || fail 'ordersvr-c compose service is missing'
grep -Fq 'profiles: ["order-cluster-c"]' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'ordersvr-c compose profile is missing'

printf '[order-cluster-c-config-test] PASS\n'
