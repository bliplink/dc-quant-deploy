#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

ENV_FILE="${TMP_DIR}/test.env"
cp "${ROOT_DIR}/.env.standalone.example" "${ENV_FILE}"
sed -i \
  -e "s#^DEPLOY_ROOT=.*#DEPLOY_ROOT=${TMP_DIR}/runtime#" \
  -e 's/^MDSVR_GW_PORT=.*/MDSVR_GW_PORT=30128/' \
  -e 's/^APSSVR_GW_PORT=.*/APSSVR_GW_PORT=30135/' \
  -e 's/^LOGINSVR_GW_PORT=.*/LOGINSVR_GW_PORT=20134/' \
  -e 's/^QUANTSVR_GW_PORT=.*/QUANTSVR_GW_PORT=30142/' \
  -e 's/^INDSVR_GW_PORT=.*/INDSVR_GW_PORT=30144/' \
  -e 's/^CUSTOMINDSVR_GW_PORT=.*/CUSTOMINDSVR_GW_PORT=30147/' \
  -e 's/^SIMSVR_GW_PORT=.*/SIMSVR_GW_PORT=30145/' \
  -e 's/^BATCHSVR_GW_PORT=.*/BATCHSVR_GW_PORT=30146/' \
  "${ENV_FILE}"

bash "${ROOT_DIR}/generate-sensitive-configs.sh" "${ENV_FILE}" >/dev/null

ATS_FILE="${TMP_DIR}/runtime/control/ATSConfig.ini"
QUANT_FILE="${TMP_DIR}/runtime/control/overrides/QuantSvr/config/application.properties"

grep -qx 'ProtoVersion=1' "${ATS_FILE}"
grep -qx 'ServerMonitor.Enable=true' "${ATS_FILE}"
grep -qx 'ServerMonitor.EnableRouteMeta=true' "${ATS_FILE}"
grep -qx 'SERVER.MDSvr.Host=127.0.0.1:30128' "${ATS_FILE}"
grep -qx 'SERVER.APSSvr.Host=127.0.0.1:30135' "${ATS_FILE}"
grep -qx 'SERVER.LoginSvr.Host=127.0.0.1:20134' "${ATS_FILE}"
grep -qx 'SERVER.QuantSvr.Host=127.0.0.1:30142' "${ATS_FILE}"
grep -qx 'SERVER.INDSvr.Host=127.0.0.1:30144' "${ATS_FILE}"
grep -qx 'SERVER.CustomindSvr.Host=127.0.0.1:30147' "${ATS_FILE}"
grep -qx 'SERVER.SIMSvr.Host=127.0.0.1:30145' "${ATS_FILE}"
grep -qx 'SERVER.BatchSvr.Host=127.0.0.1:30146' "${ATS_FILE}"

GW_CLIENT_FILE="${TMP_DIR}/runtime/control/overrides/GW/config/spring-gw-client.xml"
grep -q '<property name="serverMonitor" ref="serverMonitor" />' "${GW_CLIENT_FILE}"
grep -q '<ref bean="serverMonitor" />' "${GW_CLIENT_FILE}"
grep -q 'md.monitor.\*\*' "${GW_CLIENT_FILE}"
grep -q 'aps.monitor.\*\*' "${GW_CLIENT_FILE}"
grep -qx 'GWPort=30135' "${QUANT_FILE}"

echo 'configurable service port test passed'
