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
  printf '[trade-cluster-config-test] ERROR: %s\n' "$*" >&2
  exit 1
}

sed \
  -e "s|^DEPLOY_ROOT=.*|DEPLOY_ROOT=${TEST_ROOT}/runtime|" \
  -e 's|^TRADE_CLUSTER_ENABLED=.*|TRADE_CLUSTER_ENABLED=true|' \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/cluster.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/cluster.env" >/dev/null

ats="${TEST_ROOT}/runtime/control/ATSConfig.ini"
a_config="${TEST_ROOT}/runtime/control/overrides/TradeSvrA/config/application.properties"
b_config="${TEST_ROOT}/runtime/control/overrides/TradeSvrB/config/application.properties"
a_log="${TEST_ROOT}/runtime/control/overrides/TradeSvrA/config/log4j.ini"
b_log="${TEST_ROOT}/runtime/control/overrides/TradeSvrB/config/log4j.ini"

grep -Fqx 'ProtoVersion=2' "${ats}" || fail 'protocol v2 is not enabled'
grep -Fqx 'LBConfig.TradeSvr=Partition' "${ats}" || fail 'TradeSvr partition load balance is missing'
grep -Fqx 'Partition.TradeSvr.Root=/dc/cluster/tradesvr/partitions' "${ats}" || fail 'logical Trade root is missing'
grep -Fqx 'Partition.TradeSvrA.EnforceReadiness=true' "${ats}" || fail 'TradeSvrA readiness fence is missing'
grep -Fqx 'Partition.TradeSvrB.EnforceReadiness=true' "${ats}" || fail 'TradeSvrB readiness fence is missing'
grep -Fqx 'Partition.TradeSvr.PlacementEnabled=false' "${ats}" || fail 'logical Trade placement must stay disabled'
grep -Fqx 'Partition.TradeSvrA.PlacementEnabled=false' "${ats}" || fail 'TradeSvrA placement must stay disabled'
grep -Fqx 'Partition.TradeSvrB.PlacementEnabled=false' "${ats}" || fail 'TradeSvrB placement must stay disabled'
grep -Fqx 'Partition.TradeSvr.PlacementPath=/dc/cluster/tradesvr/desired/placement' "${ats}" ||
  fail 'Trade placement path is missing'
grep -Fqx 'serverKey=SERVER.TradeSvrA' "${a_config}" || fail 'TradeSvrA physical identity is missing'
grep -Fqx 'serverKey=SERVER.TradeSvrB' "${b_config}" || fail 'TradeSvrB physical identity is missing'
grep -Fqx 'trade.node.businessEnabled=true' "${a_config}" || fail 'TradeSvrA must be the only business node'
grep -Fqx 'trade.node.businessEnabled=false' "${b_config}" || fail 'TradeSvrB must start fenced'
grep -Fqx 'storePath=../../data/TradeSvrA' "${a_config}" || fail 'TradeSvrA data path is not isolated'
grep -Fqx 'storePath=../../data/TradeSvrB' "${b_config}" || fail 'TradeSvrB data path is not isolated'
grep -Fqx 'log4j.appender.file.File=../../log/TradeSvrA.log' "${a_log}" || fail 'TradeSvrA log path is not isolated'
grep -Fqx 'log4j.appender.file.File=../../log/TradeSvrB.log' "${b_log}" || fail 'TradeSvrB log path is not isolated'
grep -Fq 'overrides/${TRADESVR_CONFIG_NAME:-TradeSvr}/config/application.properties:/srv/dc/dc/TradeSvr/config/application.properties:ro' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'TradeSvrA selected config is not mounted'
grep -Fqx '  tradesvr-b:' "${DEPLOY_DIR}/compose.yaml" || fail 'tradesvr-b compose service is missing'
grep -Fq 'profiles: ["trade-cluster"]' "${DEPLOY_DIR}/compose.yaml" || fail 'tradesvr-b compose profile is missing'

sed '/^TRADESVR_B_GW_PORT=/d' "${TEST_ROOT}/cluster.env" > "${TEST_ROOT}/invalid.env"
if "${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/invalid.env" >/dev/null 2>&1; then
  fail 'Trade cluster must not be enabled without TRADESVR_B_GW_PORT'
fi

printf '[trade-cluster-config-test] PASS\n'
