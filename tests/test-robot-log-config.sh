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
  printf '[robot-log-config-test] ERROR: %s\n' "$*" >&2
  exit 1
}

sed -e "s|^DEPLOY_ROOT=.*|DEPLOY_ROOT=${TEST_ROOT}/runtime|" \
  "${DEPLOY_DIR}/.env.example" > "${TEST_ROOT}/robot.env"

"${DEPLOY_DIR}/generate-saas-configs.sh" "${TEST_ROOT}/robot.env" >/dev/null

robot_log="${TEST_ROOT}/runtime/control/overrides/RobotSvr/config/log4j.ini"
[[ -f "${robot_log}" ]] || fail 'RobotSvr log4j override was not generated'
grep -Fqx 'log4j.rootLogger=INFO,file,stdout' "${robot_log}" || fail 'RobotSvr root logger mismatch'
grep -Fqx 'log4j.appender.file.File=../../log/RobotSvr.log' "${robot_log}" || fail 'RobotSvr log path mismatch'
grep -Fqx 'log4j.logger.com.gateway.connector.tcp.client.GateWayApi=ERROR' "${robot_log}" ||
  fail 'RobotSvr GateWayApi sensitive reply logging must stay suppressed'
grep -Fq 'overrides/RobotSvr/config/log4j.ini:/srv/dc/dc/RobotSvr/config/log4j.ini:ro' "${DEPLOY_DIR}/compose.yaml" ||
  fail 'RobotSvr log4j override is not mounted by compose'

printf '[robot-log-config-test] PASS\n'
