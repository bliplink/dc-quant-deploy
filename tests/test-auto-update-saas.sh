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
  "${SCRIPT_DIR}/install-saas.sh" \
  "${SCRIPT_DIR}/deploy-saas.sh" \
  "${SCRIPT_DIR}/tests/recover-order-cluster-partitions-host.sh" \
  "${SCRIPT_DIR}/tests/restart-order-trade-e2e.sh" \
  "${SCRIPT_DIR}/tests/run-core-trading-acceptance.sh" \
  "${SCRIPT_DIR}/tests/run-core-trading-stress-host.sh" \
  "${SCRIPT_DIR}/tests/run-trade-cluster-role-reversal-host.sh" \
  "${SCRIPT_DIR}/uninstall-saas.sh"; do
  bash -n "${script}"
done

[[ -x "${SCRIPT_DIR}/install-saas.sh" ]] ||
  fail "install-saas.sh must be executable"

updater="${SCRIPT_DIR}/auto-update-saas.sh"
service_block="$(sed -n '/^APP_SERVICES=(/,/^)/p' "${updater}")"

for service in gateway loginsvr mdsvr apssvr ordersvr tradesvr liqsvr managersvr adminsvr robotsvr web tenant-web platform-web; do
  grep -qw "${service}" <<< "${service_block}" || fail "missing application service ${service}"
done

grep -q '\${ORDER_CLUSTER_ENABLED:-false}.*\${TRADE_CLUSTER_ENABLED:-false}' "${updater}" ||
  fail "ProjectionSvr must be tracked when either Order or Trade cluster is enabled"
grep -q 'tenant-web).*TENANT_WEB_IMAGE_REPOSITORY' "${updater}" ||
  fail "tenant web image is not tracked"
grep -q 'platform-web).*PLATFORM_WEB_IMAGE_REPOSITORY' "${updater}" ||
  fail "platform web image is not tracked"

for infrastructure in mysql clickhouse zookeeper; do
  if grep -qw "${infrastructure}" <<< "${service_block}"; then
    fail "infrastructure service ${infrastructure} must not be auto-updated"
  fi
done

grep -q 'flock -n 9' "${updater}" || fail "updater global lock is missing"
grep -q 'for service in "${changed_services\[@\]}"' "${updater}" || fail "serial pull loop is missing"
grep -q 'docker pull "${image_ref}"' "${updater}" || fail "application pull is missing"
grep -q 'rollback_images' "${updater}" || fail "rollback path is missing"
grep -q 'for ((attempt=1; attempt<=GIT_FETCH_ATTEMPTS; attempt++))' "${updater}" ||
  fail "Git fetch retry loop is missing"
grep -q 'SAAS_DEPLOY_LOCK_HELD=true' "${updater}" || fail "deploy lock handoff is missing"
grep -q '^if \[\[ "${BASH_SOURCE\[0\]}" == "\$0" \]\]; then$' "${updater}" ||
  fail "source-safe main guard is missing"
grep -q 'SAAS_AUTO_UPDATE_DEPLOY_REPO=true' "${SCRIPT_DIR}/.env.example" ||
  fail "environment defaults are missing"
grep -q 'AUTO_UPDATE.zh-CN.md' "${SCRIPT_DIR}/README.md" ||
  fail "operator documentation is not linked"

grep -Fq 'exec "${SCRIPT_DIR}/deploy-saas.sh" "$@"' "${SCRIPT_DIR}/install-saas.sh" ||
  fail "install entry point must delegate to deploy-saas.sh"
grep -Fq 'if [[ "${IMAGE_SOURCE:-local}" == "local" ]]; then' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "local image source branch is missing"
grep -Fq '"${SCRIPT_DIR}/build-saas-images.sh" "${ENV_FILE}"' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "local image source must build application images"
if grep -Fq 'migrate_env_value IMAGE_SOURCE local registry' "${SCRIPT_DIR}/deploy-saas.sh"; then
  fail "explicit local image source must not be rewritten to registry"
fi
grep -q '^verify_source_dependency_alignment()' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "local source dependency-alignment guard is missing"
grep -Fqx 'verify_source_dependency_alignment' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "local source dependency-alignment guard is not invoked"
grep -Fq 'uses a dynamic Maven dependency version (LATEST/RELEASE)' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "dynamic Maven version guard is missing"
grep -q '^prepare_local_build_identity()' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "immutable local build tag preparation is missing"
grep -Fq 'SAAS_LOCAL_BUILD_TAG:-cluster-dev-local-' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "local build tag must default to an immutable cluster-dev tag"
grep -Fq 'prepare_local_build_identity' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "local build identity preparation is not invoked"
grep -Fq 'COMMON_JAR_SHA256=${common_hash}' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "local Java images are missing com.app.common SHA-256 provenance"
grep -Fq 'COMMON_REVISION=com-app-common-v${common_version}' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "local Java images are missing com.app.common revision provenance"

for image_var in \
  GW_IMAGE_REPOSITORY LOGINSVR_IMAGE_REPOSITORY MDSVR_IMAGE_REPOSITORY APSSVR_IMAGE_REPOSITORY \
  ORDERSVR_IMAGE_REPOSITORY PROJECTIONSVR_IMAGE_REPOSITORY TRADESVR_IMAGE_REPOSITORY \
  LIQSVR_IMAGE_REPOSITORY MANAGERSVR_IMAGE_REPOSITORY ADMINSVR_IMAGE_REPOSITORY \
  ROBOTSVR_IMAGE_REPOSITORY TRADE_WEB_IMAGE_REPOSITORY TENANT_WEB_IMAGE_REPOSITORY \
  PLATFORM_WEB_IMAGE_REPOSITORY; do
  grep -Fq "\${${image_var}" "${SCRIPT_DIR}/build-saas-images.sh" ||
    fail "local image builder does not produce compose image variable ${image_var}"
done
grep -Fqx 'recover_order_cluster_if_needed' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "staged OrderSvr recovery is not invoked"
grep -Fq 'docker logs --since "${a_started}" dc-saas-ordersvr' "${SCRIPT_DIR}/deploy-saas.sh" ||
  fail "OrderSvr readiness is not scoped to the current process incarnation"

grep -q 'ORDER_CLUSTER_RESTART_AFTER_FENCE=true' "${SCRIPT_DIR}/tests/restart-order-trade-e2e.sh" ||
  fail "E2E restart does not fence the new epoch before restarting OrderSvr"
grep -q '^snapshot_projection_watermarks()' "${SCRIPT_DIR}/tests/restart-order-trade-e2e.sh" ||
  fail "projection watermark snapshot is missing from restart acceptance"
grep -q 'verify_projection_watermarks_not_regressed' "${SCRIPT_DIR}/tests/restart-order-trade-e2e.sh" ||
  fail "projection watermark continuity check is missing from restart acceptance"
grep -q '^verify_projection_watermarks_advanced()' "${SCRIPT_DIR}/tests/restart-order-trade-e2e.sh" ||
  fail "projection advancement helper is missing"
grep -q 'verify_projection_watermarks_advanced' "${SCRIPT_DIR}/tests/run-core-trading-acceptance.sh" ||
  fail "projection advancement check is missing from core trading acceptance"
grep -q 'Fence confirmed; restarting OrderSvr cluster and TradeSvr inside epoch' \
  "${SCRIPT_DIR}/tests/recover-order-cluster-partitions-host.sh" ||
  fail "cluster recovery does not own the fenced restart boundary"

printf 'PASS: SaaS deploy/update static checks\n'
