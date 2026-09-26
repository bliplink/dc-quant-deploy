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
  printf '[service-log-config-test] ERROR: %s\n' "$*" >&2
  exit 1
}

assert_standard_log() {
  local node="$1" file="${TEST_ROOT}/runtime/control/overrides/${node}/config/log4j.ini"
  [[ -f "${file}" ]] || fail "${node} log4j override was not generated"
  grep -Fqx 'log4j.rootLogger=INFO,file,stdout' "${file}" || fail "${node} root logger is not INFO,file,stdout"
  grep -Fqx 'log4j.logger.com.gateway.connector.tcp.client.GateWayApi=ERROR' "${file}" || fail "${node} GateWayApi sensitive logging is not suppressed"
  grep -Fqx 'log4j.logger.com.gw.common.utils.GwServerResource=WARN' "${file}" || fail "${node} market-data payload logging is not suppressed"
  grep -Fqx 'log4j.logger.com.gw.common.utils=WARN' "${file}" || fail "${node} proxied GwServerResource payload logging is not suppressed"
  grep -Fqx 'log4j.appender.file=org.apache.log4j.DailyRollingFileAppender' "${file}" || fail "${node} file appender is not DailyRollingFileAppender"
  grep -Fqx "log4j.appender.file.File=../../log/${node}.log" "${file}" || fail "${node} log path mismatch"
  grep -Fqx 'log4j.appender.stdout=org.apache.log4j.ConsoleAppender' "${file}" || fail "${node} stdout appender missing"
  grep -Fqx 'log4j.appender.stdout.Target=System.out' "${file}" || fail "${node} stdout target mismatch"
}

sed -e "s|^DEPLOY_ROOT=.*|DEPLOY_ROOT=${TEST_ROOT}/runtime|" \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/service-log.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/service-log.env" >/dev/null
for node in GW LoginSvr APSSvr OrderSvr ProjectionSvr LiqSvr ManagerSvr AdminSvr RobotSvr; do
  assert_standard_log "${node}"
done

# Exercise clustered node naming too. Later assignments win when the env file is sourced.
cat >> "${TEST_ROOT}/service-log.env" <<'EOF'
ORDER_CLUSTER_ENABLED=true
ORDER_CLUSTER_C_ENABLED=true
MD_CLUSTER_ENABLED=true
MD_CLUSTER_C_ENABLED=true
TRADE_CLUSTER_ENABLED=true
EOF
rm -rf "${TEST_ROOT}/runtime/control/overrides"
"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/service-log.env" >/dev/null
for node in OrderSvrA OrderSvrB OrderSvrC; do
  assert_standard_log "${node}"
done
for node in MDSvrA MDSvrB MDSvrC TradeSvrA TradeSvrB; do
  file="${TEST_ROOT}/runtime/control/overrides/${node}/config/log4j.ini"
  [[ -f "${file}" ]] || fail "${node} cluster log4j override was not generated"
  grep -Fqx 'log4j.logger.com.gateway.connector.tcp.client.GateWayApi=ERROR' "${file}" || fail "${node} GateWayApi sensitive logging is not suppressed"
  grep -Fqx 'log4j.logger.com.gw.common.utils.GwServerResource=WARN' "${file}" || fail "${node} market-data payload logging is not suppressed"
  grep -Fqx 'log4j.logger.com.gw.common.utils=WARN' "${file}" || fail "${node} proxied GwServerResource payload logging is not suppressed"
  grep -Fq "log4j.appender.file.File=../../log/${node}.log" "${file}" || fail "${node} log path mismatch"
  grep -Fq 'log4j.appender.stdout=org.apache.log4j.ConsoleAppender' "${file}" || fail "${node} stdout appender missing"
done

# Every Java service/node that writes the shared log directory must mount a deploy-managed log4j.ini.
missing="$({
  awk '
    /^  [A-Za-z0-9_-]+:$/ {svc=$1; sub(":$","",svc)}
    /\/srv\/dc\/log$/ {shared[svc]=1}
    /\/config\/log4j\.ini:ro$/ {cfg[svc]=1}
    END {for (s in shared) if (s != "volumes" && !cfg[s]) print s}
  ' "${DEPLOY_DIR}/compose.yaml"
} | sort)"
[[ -z "${missing}" ]] || fail "services missing log4j mount: ${missing//$'\n'/,}"

grep -Fq 'JAVA_TOOL_OPTIONS: ${APSSVR_EXTRA_JAVA_OPTS:-}' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'APSSvr optional JVM proxy options are not wired through JAVA_TOOL_OPTIONS'

printf '[service-log-config-test] PASS\n'
