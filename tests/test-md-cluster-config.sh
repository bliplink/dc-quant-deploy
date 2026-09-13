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
  -e 's|^MD_CLUSTER_C_ENABLED=.*|MD_CLUSTER_C_ENABLED=true|' \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/cluster.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/cluster.env" >/dev/null

ats="${TEST_ROOT}/runtime/control/ATSConfig.ini"
a_config="${TEST_ROOT}/runtime/control/overrides/MDSvrA/config/application.properties"
b_config="${TEST_ROOT}/runtime/control/overrides/MDSvrB/config/application.properties"
c_config="${TEST_ROOT}/runtime/control/overrides/MDSvrC/config/application.properties"
c_log="${TEST_ROOT}/runtime/control/overrides/MDSvrC/config/log4j.ini"

grep -Fqx 'ProtoVersion=2' "${ats}" || fail 'protocol v2 is not enabled'
grep -Fqx 'LBConfig.MDSvr=Partition' "${ats}" || fail 'MDSvr partition load balance is missing'
grep -Fqx 'Partition.MDSvr.Root=/dc/cluster/mdsvr/partitions' "${ats}" || fail 'logical MD root is missing'
grep -Fqx 'Partition.MDSvrA.EnforceReadiness=true' "${ats}" || fail 'MDSvrA readiness fence is missing'
grep -Fqx 'Partition.MDSvrB.EnforceReadiness=true' "${ats}" || fail 'MDSvrB readiness fence is missing'
grep -Fqx 'Partition.MDSvrC.EnforceReadiness=true' "${ats}" || fail 'MDSvrC readiness fence is missing'
grep -Fqx 'Partition.MDSvr.PlacementEnabled=false' "${ats}" || fail 'logical MD placement must stay disabled'
grep -Fqx 'Partition.MDSvrA.PlacementEnabled=false' "${ats}" || fail 'MDSvrA placement must stay disabled'
grep -Fqx 'Partition.MDSvrB.PlacementEnabled=false' "${ats}" || fail 'MDSvrB placement must stay disabled'
grep -Fqx 'Partition.MDSvrC.PlacementEnabled=false' "${ats}" || fail 'MDSvrC placement must stay disabled'
grep -Fqx 'Partition.MDSvr.PlacementPath=/dc/cluster/mdsvr/desired/placement' "${ats}" || fail 'MD placement path is missing'
grep -Fqx 'serverKey=SERVER.MDSvrA' "${a_config}" || fail 'MDSvrA physical identity is missing'
grep -Fqx 'serverKey=SERVER.MDSvrB' "${b_config}" || fail 'MDSvrB physical identity is missing'
grep -Fqx 'serverKey=SERVER.MDSvrC' "${c_config}" || fail 'MDSvrC physical identity is missing'
grep -Fqx 'ohlcStorePath=../../data/MDSvrA/ohlc' "${a_config}" || fail 'MDSvrA data path is not isolated'
grep -Fqx 'ohlcStorePath=../../data/MDSvrB/ohlc' "${b_config}" || fail 'MDSvrB data path is not isolated'
grep -Fqx 'ohlcStorePath=../../data/MDSvrC/ohlc' "${c_config}" || fail 'MDSvrC data path is not isolated'
grep -Fqx 'log4j.logger.com.app.dc.service.cluster.MdPartitionRuntime=INFO,file,stdout' "${c_log}" ||
  fail 'MDSvr cluster readiness logger is not observable'
grep -Fqx 'log4j.appender.file.File=../../log/MDSvrC.log' "${c_log}" ||
  fail 'MDSvrC log path is not isolated'
grep -Fq 'overrides/MDSvrC/config/log4j.ini:/srv/dc/dc/MDSvr/config/log4j.ini:ro' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'MDSvrC generated logger config is not mounted'
grep -Fqx '  mdsvr-c:' "${DEPLOY_DIR}/compose.yaml" || fail 'mdsvr-c compose service is missing'
grep -Fq 'profiles: ["md-cluster-c"]' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'mdsvr-c compose profile is missing'

sed \
  -e "s|^DEPLOY_ROOT=.*|DEPLOY_ROOT=${TEST_ROOT}/invalid-runtime|" \
  -e 's|^MD_CLUSTER_C_ENABLED=.*|MD_CLUSTER_C_ENABLED=true|' \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/invalid.env"
if "${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/invalid.env" >/dev/null 2>&1; then
  fail 'MDSvrC must not be enabled without the base MD cluster'
fi

printf '[md-cluster-config-test] PASS\n'
