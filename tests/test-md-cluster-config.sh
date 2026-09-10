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
  printf '[md-cluster-config-test] ERROR: %s\n' "$*" >&2
  exit 1
}

sed \
  -e "s|^DEPLOY_ROOT=.*|DEPLOY_ROOT=${TEST_ROOT}/runtime|" \
  -e 's|^MD_CLUSTER_ENABLED=.*|MD_CLUSTER_ENABLED=true|' \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/cluster.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/cluster.env" >/dev/null

ats="${TEST_ROOT}/runtime/control/ATSConfig.ini"
a_config="${TEST_ROOT}/runtime/control/overrides/MDSvrA/config/application.properties"
b_config="${TEST_ROOT}/runtime/control/overrides/MDSvrB/config/application.properties"

grep -Fqx 'ProtoVersion=2' "${ats}" || fail 'protocol v2 is not enabled'
grep -Fqx 'LBConfig.MDSvr=Partition' "${ats}" || fail 'MDSvr partition load balance is missing'
grep -Fqx 'Partition.MDSvr.Root=/dc/cluster/mdsvr/partitions' "${ats}" || fail 'logical MD root is missing'
grep -Fqx 'Partition.MDSvrA.EnforceReadiness=true' "${ats}" || fail 'MDSvrA readiness fence is missing'
grep -Fqx 'Partition.MDSvrB.EnforceReadiness=true' "${ats}" || fail 'MDSvrB readiness fence is missing'
grep -Fqx 'serverKey=SERVER.MDSvrA' "${a_config}" || fail 'MDSvrA physical identity is missing'
grep -Fqx 'serverKey=SERVER.MDSvrB' "${b_config}" || fail 'MDSvrB physical identity is missing'
grep -Fqx 'ohlcStorePath=../../data/MDSvrA/ohlc' "${a_config}" || fail 'MDSvrA data path is not isolated'
grep -Fqx 'ohlcStorePath=../../data/MDSvrB/ohlc' "${b_config}" || fail 'MDSvrB data path is not isolated'

printf '[md-cluster-config-test] PASS\n'
