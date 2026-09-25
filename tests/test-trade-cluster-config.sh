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
grep -Fqx 'trade.node.businessEnabled=true' "${a_config}" || fail 'TradeSvrA hot runtime must be enabled'
grep -Fqx 'trade.node.businessEnabled=true' "${b_config}" || fail 'TradeSvrB hot runtime must be enabled'
grep -Fqx 'trade.cluster.journal.enabled=true' "${a_config}" || fail 'TradeSvrA journal must be enabled'
grep -Fqx 'trade.cluster.journal.enabled=true' "${b_config}" || fail 'TradeSvrB journal must be enabled'
grep -Fqx 'trade.cluster.state.commit.enabled=true' "${a_config}" || fail 'Trade commit markers must be enabled'
grep -Fqx 'trade.cluster.state.required=true' "${a_config}" || fail 'Trade authoritative state must fail closed'
grep -Fqx 'trade.cluster.snapshot.enabled=true' "${a_config}" || fail 'Trade snapshot must be enabled'
grep -Fqx 'trade.cluster.lifecycle.enabled=true' "${a_config}" || fail 'Trade recovery lifecycle must be enabled'
grep -Fqx 'trade.cluster.recovery.authoritative=true' "${a_config}" || fail 'Trade authoritative recovery must be enabled'
grep -Fqx 'trade.cluster.replication.enabled=true' "${a_config}" || fail 'Trade replication must be enabled'
grep -Fqx 'trade.cluster.replication.required=false' "${a_config}" || fail 'TradeSvrA replica ACK must not gate Primary availability'
grep -Fqx 'trade.cluster.replication.required=false' "${b_config}" || fail 'TradeSvrB replica ACK must not gate Primary availability'
grep -Fqx 'trade.cluster.replication.degradedRetryMillis=1000' "${a_config}" || fail 'Trade replica degraded retry interval mismatch'
grep -Fqx 'trade.cluster.replication.requestTimeoutMs=1000' "${a_config}" || fail 'Trade replica timeout must stay bounded during replica outage'
grep -Fqx 'trade.cluster.replication.port=19221' "${a_config}" || fail 'TradeSvrA replication port mismatch'
grep -Fqx 'trade.cluster.replication.port=19222' "${b_config}" || fail 'TradeSvrB replication port mismatch'
grep -Fqx 'trade.cluster.replication.peers=TradeSvrA=127.0.0.1:19221,TradeSvrB=127.0.0.1:19222' "${a_config}" ||
  fail 'Trade replication peers are missing'
grep -Fqx 'trade.projection.binary.enabled=true' "${a_config}" || fail 'Trade binary Projection publisher must be enabled'
grep -Fqx 'storePath=../../data/TradeSvrA' "${a_config}" || fail 'TradeSvrA data path is not isolated'
grep -Fqx 'storePath=../../data/TradeSvrB' "${b_config}" || fail 'TradeSvrB data path is not isolated'
grep -Fqx 'log4j.appender.file.File=../../log/TradeSvrA.log' "${a_log}" || fail 'TradeSvrA log path is not isolated'
grep -Fqx 'log4j.appender.file.File=../../log/TradeSvrB.log' "${b_log}" || fail 'TradeSvrB log path is not isolated'
grep -Fq 'overrides/${TRADESVR_CONFIG_NAME:-TradeSvr}/config/application.properties:/srv/dc/dc/TradeSvr/config/application.properties:ro' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'TradeSvrA selected config is not mounted'
grep -Fqx '  tradesvr-b:' "${DEPLOY_DIR}/compose.yaml" || fail 'tradesvr-b compose service is missing'
grep -Fq 'profiles: ["trade-cluster"]' "${DEPLOY_DIR}/compose.yaml" || fail 'tradesvr-b compose profile is missing'
grep -Fq 'profiles: ["order-cluster", "trade-cluster"]' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'ProjectionSvr must start for the trade-cluster profile'
projection_config="${TEST_ROOT}/runtime/control/overrides/ProjectionSvr/config/application.properties"
grep -Fqx 'projection.trade.binary.enabled=true' "${projection_config}" ||
  fail 'ProjectionSvr Trade binary consumer must be enabled'
grep -Fqx 'projection.trade.binary.tradeServerKey=SERVER.TradeSvr' "${projection_config}" ||
  fail 'ProjectionSvr Trade logical server key is missing'
grep -Fq 'wait_for_port "${TRADESVR_A_REPLICATION_PORT}" tradesvr 180' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'TradeSvrA replication readiness wait is missing'
grep -Fq 'wait_for_port "${TRADESVR_B_REPLICATION_PORT}" tradesvr-b 180' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'TradeSvrB replication readiness wait is missing'
grep -Fq 'wait_for_trade_cluster_readiness' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'Trade cluster readiness gate is missing from deployment'
grep -Fq '"${ORDER_CLUSTER_ENABLED:-false}" == "true" || "${TRADE_CLUSTER_ENABLED:-false}" == "true"' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'ProjectionSvr deployment wait must cover Trade cluster mode'
grep -Fq 'expected_containers+=(dc-saas-projectionsvr)' "${DEPLOY_DIR}/validate-saas.sh" ||
  fail 'runtime validation must require ProjectionSvr in clustered Trade mode'
grep -Fq "trade.node.businessEnabled=true" "${DEPLOY_DIR}/validate-saas.sh" ||
  fail 'runtime validation must require the TradeSvrB hot runtime'
grep -Fq "projection.trade.binary.enabled=true" "${DEPLOY_DIR}/validate-saas.sh" ||
  fail 'runtime validation must require the Trade Projection consumer'

sed '/^TRADESVR_B_GW_PORT=/d' "${TEST_ROOT}/cluster.env" > "${TEST_ROOT}/invalid.env"
if "${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/invalid.env" >/dev/null 2>&1; then
  fail 'Trade cluster must not be enabled without TRADESVR_B_GW_PORT'
fi

sed '/^TRADESVR_A_REPLICATION_PORT=/d' "${TEST_ROOT}/cluster.env" > "${TEST_ROOT}/invalid-replication.env"
if "${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/invalid-replication.env" >/dev/null 2>&1; then
  fail 'Trade cluster must not be enabled without TRADESVR_A_REPLICATION_PORT'
fi

grep -Fq -- '--full-cluster)' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'one-command full cluster option is missing'
grep -Fq 'set_env_value MD_CLUSTER_ENABLED true' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'full cluster must enable MD cluster'
grep -Fq 'set_env_value MD_CLUSTER_C_ENABLED true' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'full cluster must enable MDSvrC'
grep -Fq 'set_env_value ORDER_CLUSTER_ENABLED true' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'full cluster must enable Order cluster'
grep -Fq 'set_env_value ORDER_CLUSTER_C_ENABLED false' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'full cluster topology must keep OrderSvr at A/B'
grep -Fq 'set_env_value TRADE_CLUSTER_ENABLED true' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'full cluster must enable Trade cluster'
grep -Fq 'apply_full_cluster_profile' "${DEPLOY_DIR}/deploy-saas.sh" ||
  fail 'full cluster profile must be applied before deployment'

printf '[trade-cluster-config-test] PASS\n'
