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
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/cluster.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/cluster.env" >/dev/null

ats="${TEST_ROOT}/runtime/control/ATSConfig.ini"
a_config="${TEST_ROOT}/runtime/control/overrides/OrderSvrA/config/application.properties"
b_config="${TEST_ROOT}/runtime/control/overrides/OrderSvrB/config/application.properties"
c_config="${TEST_ROOT}/runtime/control/overrides/OrderSvrC/config/application.properties"
peers='order.cluster.replication.peers=OrderSvrA=127.0.0.1:19121,OrderSvrB=127.0.0.1:19122,OrderSvrC=127.0.0.1:19123'

grep -Fqx 'SERVER.OrderSvrC.Name=OrderSvrC' "${ats}" || fail 'OrderSvrC server registration is missing'
grep -Fqx 'Partition.OrderSvrC.EnforceReadiness=true' "${ats}" || fail 'OrderSvrC readiness fence is missing'
grep -Fqx 'serverKey=SERVER.OrderSvrC' "${c_config}" || fail 'OrderSvrC physical identity is missing'
grep -Fqx 'orderStorePath=../../data/OrderSvrC/store' "${c_config}" || fail 'OrderSvrC data path is not isolated'
grep -Fqx 'order.cluster.replication.port=19123' "${c_config}" || fail 'OrderSvrC replication port is missing'
grep -Fqx 'order.cluster.snapshot.periodic.enabled=true' "${c_config}" || fail 'periodic snapshots are not enabled'
for config in "${a_config}" "${b_config}" "${c_config}"; do
  grep -Fqx "${peers}" "${config}" || fail "three-node peer map is missing from ${config}"
done

grep -Fqx '  ordersvr-c:' "${DEPLOY_DIR}/compose.yaml" || fail 'ordersvr-c compose service is missing'
grep -Fq 'profiles: ["order-cluster-c"]' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'ordersvr-c compose profile is missing'

printf '[order-cluster-c-config-test] PASS\n'
