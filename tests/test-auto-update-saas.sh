#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

for script in \
  "${SCRIPT_DIR}/auto-update-saas.sh" \
  "${SCRIPT_DIR}/install-auto-update-cron.sh" \
  "${SCRIPT_DIR}/deploy-saas.sh" \
  "${SCRIPT_DIR}/uninstall-saas.sh"; do
  bash -n "${script}"
done

updater="${SCRIPT_DIR}/auto-update-saas.sh"
service_block="$(sed -n '/^APP_SERVICES=(/,/^)/p' "${updater}")"

for service in gateway loginsvr mdsvr apssvr ordersvr tradesvr liqsvr managersvr adminsvr web; do
  grep -qw "${service}" <<< "${service_block}" || fail "missing application service ${service}"
done

for infrastructure in mysql clickhouse zookeeper; do
  if grep -qw "${infrastructure}" <<< "${service_block}"; then
    fail "infrastructure service ${infrastructure} must not be auto-updated"
  fi
done

grep -q 'flock -n 9' "${updater}" || fail "updater global lock is missing"
grep -q 'for service in "${changed_services\[@\]}"' "${updater}" || fail "serial pull loop is missing"
grep -q 'docker pull "${image_ref}"' "${updater}" || fail "application pull is missing"
grep -q 'rollback_images' "${updater}" || fail "rollback path is missing"
grep -q 'for ((attempt=1; attempt<=GIT_FETCH_ATTEMPTS; attempt++))' "${updater}" || fail "Git fetch retry loop is missing"
grep -q 'SAAS_DEPLOY_LOCK_HELD=true' "${updater}" || fail "deploy lock handoff is missing"
grep -q '^if \[\[ "${BASH_SOURCE\[0\]}" == "\$0" \]\]; then$' "${updater}" || fail "source-safe main guard is missing"
grep -q 'SAAS_AUTO_UPDATE_DEPLOY_REPO=true' "${SCRIPT_DIR}/.env.example" || fail "environment defaults are missing"
grep -q 'AUTO_UPDATE.zh-CN.md' "${SCRIPT_DIR}/README.md" || fail "operator documentation is not linked"

printf 'PASS: SaaS auto-update static checks\n'
