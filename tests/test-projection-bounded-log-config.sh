#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp="$(mktemp -d)"
trap 'rm -rf "${temp}"' EXIT
export OVERRIDE_ROOT="${temp}/config"
install -d -m 0750 "${OVERRIDE_ROOT}/ProjectionSvr/config"
# Only execute the self-contained generation function. No live runtime,
# Docker, DB, public ports, or secrets are touched by this unit test.
sed -n '/^write_projection_log_config() {/,/^}/p' "${root}/generate-saas-configs.sh" > "${temp}/policy.sh"
bash -n "${temp}/policy.sh"
source "${temp}/policy.sh"
declare -F write_projection_log_config >/dev/null
write_projection_log_config
file="${OVERRIDE_ROOT}/ProjectionSvr/config/log4j.ini"
test -f "${file}"
grep -Fxq 'log4j.rootLogger=INFO,file,stdout' "${file}"
grep -Fxq 'log4j.logger.com.app.dc.projection.OrderProjectionBinaryConsumer=ERROR' "${file}"
grep -Fxq 'log4j.appender.file=org.apache.log4j.RollingFileAppender' "${file}"
grep -Fxq 'log4j.appender.file.MaxFileSize=20MB' "${file}"
grep -Fxq 'log4j.appender.file.MaxBackupIndex=4' "${file}"
if grep -Fq 'DailyRollingFileAppender' "${file}"; then
  echo "unbounded daily Projection log regression" >&2
  exit 1
fi
echo PROJECTION_LOG_POLICY_BOUNDED_AND_RETRY_SPAM_SUPPRESSED_PASS
