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
  "${SCRIPT_DIR}/acceptance-saas.sh" \
  "${SCRIPT_DIR}/tests/recover-order-cluster-partitions-host.sh" \
  "${SCRIPT_DIR}/tests/restart-order-trade-e2e.sh" \
  "${SCRIPT_DIR}/tests/prepare-web-trading-e2e.sh" \
  "${SCRIPT_DIR}/tests/run-web-trading-e2e-host.sh" \
  "${SCRIPT_DIR}/tests/run-core-trading-acceptance.sh" \
  "${SCRIPT_DIR}/tests/run-core-trading-stress-host.sh" \
  "${SCRIPT_DIR}/tests/run-trade-cluster-role-reversal-host.sh" \
  "${SCRIPT_DIR}/uninstall-saas.sh"; do
  bash -n "${script}"
done

[[ -x "${SCRIPT_DIR}/install-saas.sh" ]] ||
  fail "install-saas.sh must be executable"

[[ -x "${SCRIPT_DIR}/acceptance-saas.sh" ]] ||
  fail "acceptance-saas.sh must be executable"

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
grep -Fq 'sync_repo gateway-api https://github.com/bliplink/gateway-api.git gateway-api-java-v3.0.6' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "local builder is missing the pinned gateway-api source"
grep -Fq 'run_maven "${SRC_ROOT}/gateway-api/gateway-api-java/gateway-api" clean install -DskipTests' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "local builder must install gateway-api before com.app.dc"
grep -q '^prepare_git_auth()' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "private source Git authentication helper is missing"
grep -Fq 'SOURCE_GIT_TOKEN in the protected runtime environment' "${SCRIPT_DIR}/build-saas-images.sh" ||
  fail "private source clone failure does not explain SOURCE_GIT_TOKEN"
grep -Fq 'SOURCE_GIT_TOKEN' "${SCRIPT_DIR}/README.md" ||
  fail "private local source authentication is undocumented"
grep -Fq 'tenantUserRegistration' "${SCRIPT_DIR}/tests/prepare-web-trading-e2e.sh" ||
  fail "core trading acceptance must create users through the public registration handler"
grep -Fq 'E2E_BUYER_ID' "${SCRIPT_DIR}/tests/run-web-trading-e2e-host.sh" ||
  fail "browser trading acceptance does not resolve registered user identities"
grep -Fq 'tests/run-core-trading-acceptance.sh' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "unified acceptance does not run the core business flow"
grep -Fq 'tests/run-core-trading-stress-host.sh' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "unified acceptance does not run the mandatory core pressure gate"
grep -Fq 'ACCEPTANCE_STRESS_ORDERS:-1000' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "full acceptance pressure order baseline is missing"
grep -Fq 'ACCEPTANCE_STRESS_CONCURRENCY:-16' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "full acceptance pressure concurrency baseline is missing"
grep -Fq 'LOAD_ARTIFACT_DIR="${EVIDENCE_DIR}/stress"' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "pressure evidence is not retained with the acceptance report"
grep -Fq 'tests/run-tenant-lifecycle-web-e2e-host.sh' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "unified acceptance does not run tenant/platform lifecycle business validation"
grep -Fq 'tenant-platform-console-e2e.js' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-web-e2e-host.sh" ||
  fail "tenant lifecycle acceptance does not exercise standalone tenant/platform consoles"
grep -Fq 'tenantApiKeyAdmin' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-e2e-host.sh" ||
  fail "tenant lifecycle acceptance does not create a Tenant Service API key"
grep -Fq 'signed_api_call' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-e2e-host.sh" ||
  fail "tenant lifecycle acceptance does not test signed GW /api authentication"
grep -Fq 'TenantAPI OrderSvr access' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-e2e-host.sh" ||
  fail "tenant lifecycle acceptance does not reject TenantAPI trading access"
grep -Fq 'Trader API session cannot use Tenant Admin role' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-e2e-host.sh" ||
  fail "tenant lifecycle acceptance does not reject Trader API tenant-control access"
grep -Fq 'queryAccountBalance' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-e2e-host.sh" ||
  fail "tenant lifecycle acceptance does not reject TenantAPI account access"
grep -Fq 'http://127.0.0.1:18092' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-web-e2e-host.sh" ||
  fail "standalone Tenant Web is not exercised"
grep -Fq 'http://127.0.0.1:18090' "${SCRIPT_DIR}/tests/run-tenant-lifecycle-web-e2e-host.sh" ||
  fail "standalone Platform Web is not exercised"
grep -Fq 'tests/run-robot-liquidity-e2e-host.sh' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "unified acceptance does not run RobotSvr liquidity business validation"
grep -Fq 'tests/run-trade-cluster-role-reversal-host.sh' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "unified acceptance does not exercise TradeSvr role reversal"
[[ "$(grep -Fc 'validate-saas.sh' "${SCRIPT_DIR}/acceptance-saas.sh")" -ge 2 ]] ||
  fail "unified acceptance must validate health before and after business/failover tests"
grep -Fq 'acceptance-summary.json' "${SCRIPT_DIR}/acceptance-saas.sh" ||
  fail "unified acceptance does not write a summary artifact"
grep -Fq 'sudo ./acceptance-saas.sh' "${SCRIPT_DIR}/README.md" ||
  fail "full business acceptance command is undocumented"
grep -Fq 'Crypto Open API v1' "${SCRIPT_DIR}/README.md" ||
  fail "Crypto Open API documentation is not linked from README"
grep -Fq 'POST /api' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Crypto Open API signed GW transport is missing"
grep -Fq 'POST /httpapi/' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Crypto Open API session GW transport is missing"
grep -Fq 'tenantUserAdmin' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Tenant API contract is missing"
grep -Fq '受控的 scope 子集' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Open API v1 controlled scope-subset policy is undocumented"
grep -Fq '逐方法运行时门禁' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Open API stage-two runtime scope enforcement is undocumented"
grep -Fq 'com.app.gw.security.OpenApiRateLimitSecurityCheck' "${SCRIPT_DIR}/generate-saas-configs.sh" ||
  fail "generated SaaS GW config is missing the Open API rate-limit policy"
grep -Fq '<property name="traderStandardQps" value="100"/>' "${SCRIPT_DIR}/generate-saas-configs.sh" &&
grep -Fq '<property name="traderStandardBurst" value="30"/>' "${SCRIPT_DIR}/generate-saas-configs.sh" &&
grep -Fq '<property name="tenantStandardQps" value="20"/>' "${SCRIPT_DIR}/generate-saas-configs.sh" &&
grep -Fq '<property name="tenantStandardBurst" value="10"/>' "${SCRIPT_DIR}/generate-saas-configs.sh" ||
  fail "generated SaaS GW rate-limit profile values are incomplete"
grep -Fq 'TRADER_STANDARD = 100 req/s' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" &&
grep -Fq 'TENANT_STANDARD = 20 req/s' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Open API rate-limit profile deployment policy is undocumented"
grep -Fq '成功创建 API/TenantAPI Session 后更新' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" &&
grep -Fq '不在每笔订单、行情、账户等 Session 业务请求上写数据库' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "Open API last_used_time runtime policy is undocumented"
grep -Fq 'last_used_time' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" &&
! grep -Fq '1. `last_used_time` 更新' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "Open API last_used_time is still listed as a GA TODO"
grep -Fq '<property name="openApiRateLimitSecurityCheck" ref="openApiRateLimitSecurityCheck"/>' "${SCRIPT_DIR}/generate-saas-configs.sh" ||
  fail "generated SaaS GW proxy is missing Open API response-sanitizer session policy wiring"
grep -Fq '9000 / INTERNAL_ERROR' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" &&
grep -Fq '### 12.1 Open API v1 公共错误码白名单' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" &&
grep -Fq '| 10004 | `ACCESS_DENIED` |' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" &&
grep -Fq '| 10003 | `RATE_LIMIT_EXCEEDED` |' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "Open API public error whitelist is undocumented"
! grep -Fq '1. API 错误码公开白名单' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "Open API public error whitelist is still listed as a GA TODO"
grep -Fq 'Non-zero' "${SCRIPT_DIR}/docs/openapi/crypto-openapi-v1.yaml" &&
grep -Fq '            - 10005' "${SCRIPT_DIR}/docs/openapi/crypto-openapi-v1.yaml" &&
grep -Fq 'SQL, stack traces, file paths' "${SCRIPT_DIR}/docs/openapi/crypto-openapi-v1.yaml" ||
  fail "OpenAPI YAML does not lock the public error-code boundary"
! grep -Fq 'OpenApiSvr-' "${SCRIPT_DIR}/docs/CRYPTO_OPEN_API_V1.zh-CN.md" ||
  fail "obsolete OpenApiSvr topology is still documented"
grep -Fq '/api:' "${SCRIPT_DIR}/docs/openapi/crypto-openapi-v1.yaml" ||
  fail "OpenAPI spec does not describe the native /api transport"
grep -Fq '/httpapi/:' "${SCRIPT_DIR}/docs/openapi/crypto-openapi-v1.yaml" ||
  fail "OpenAPI spec does not describe the native /httpapi/ transport"
grep -Fq 'tenantApiKeyAdmin' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "field-level Open API reference does not document tenant API keys"
grep -Fq 'dc.trade.accountbalance.<UserID>.<Location>' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "field-level Open API reference does not document account topics"
grep -Fq 'dc.order.trade.<SecurityID>.*.<UserID>.<Location>' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "field-level Open API reference does not document execution topics"
! grep -Fq 'OpenApiSvr-' "${SCRIPT_DIR}/docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md" ||
  fail "field-level Open API reference still depends on obsolete OpenApiSvr topology"
grep -Fq 'MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE' "${SCRIPT_DIR}/mysql/migrations/20260919_open_api_key_policy.sql" ||
  fail "Open API trader permission defaults are missing"
grep -Fq "open_api_key_policy_columns" "${SCRIPT_DIR}/validate-saas.sh" ||
  fail "runtime validation does not require the Open API key policy schema"
grep -Fq 'Trade Web: `18088`' "${SCRIPT_DIR}/README.md" ||
  fail "README does not document the current Trade Web port"
grep -Fq 'Platform Web: `18090`' "${SCRIPT_DIR}/README.md" ||
  fail "README does not document the current Platform Web port"
grep -Fq 'Tenant Web: `18092`' "${SCRIPT_DIR}/README.md" ||
  fail "README does not document the current Tenant Web port"
grep -Fq 'Historical acceptance evidence' "${SCRIPT_DIR}/README.md" ||
  fail "README does not distinguish current runbooks from historical reports"
grep -Fq 'http://127.0.0.1:18088/' "${SCRIPT_DIR}/docs/USER_GUIDE.zh-CN.md" ||
  fail "user guide does not document the current Trade Web endpoint"
grep -Fq 'http://127.0.0.1:18090/' "${SCRIPT_DIR}/docs/USER_GUIDE.zh-CN.md" ||
  fail "user guide does not document the current Platform Web endpoint"
grep -Fq 'http://127.0.0.1:18092/?location=<你的 location>' "${SCRIPT_DIR}/docs/USER_GUIDE.zh-CN.md" ||
  fail "user guide does not document the current Tenant Web endpoint"
! grep -Fq '127.0.0.1:18089' "${SCRIPT_DIR}/docs/USER_GUIDE.zh-CN.md" ||
  fail "user guide still documents the obsolete fixed 18089 tunnel"
grep -Fq 'compose.yaml` 当前定义 22 个服务槽位' "${SCRIPT_DIR}/SAAS_IMPLEMENTATION_PLAN.md" ||
  fail "implementation plan does not describe the current compose topology"
! grep -Fq '部署基线为 13 个容器' "${SCRIPT_DIR}/SAAS_IMPLEMENTATION_PLAN.md" ||
  fail "implementation plan still contains the obsolete 13-container baseline"
! grep -Fq './validate.sh' "${SCRIPT_DIR}/CONTRIBUTING.md" ||
  fail "CONTRIBUTING still points to the removed validate.sh"
grep -Fq 'Tenant Web' "${SCRIPT_DIR}/docs/AUTO_UPDATE.zh-CN.md" &&
grep -Fq 'Platform Web' "${SCRIPT_DIR}/docs/AUTO_UPDATE.zh-CN.md" &&
grep -Fq 'ProjectionSvr' "${SCRIPT_DIR}/docs/AUTO_UPDATE.zh-CN.md" ||
  fail "auto-update documentation does not describe the current application set"

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
