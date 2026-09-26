#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.prod"

log() {
  printf '[saas-validate] %s\n' "$*"
}

die() {
  printf '[saas-validate] ERROR: %s\n' "$*" >&2
  exit 1
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --env-file)
      shift
      [[ "$#" -gt 0 ]] || die "--env-file requires a path"
      ENV_FILE="$1"
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

profiles=()
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
  profiles+=(order-cluster)
  export ORDERSVR_CONFIG_NAME=OrderSvrA
  if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    profiles+=(order-cluster-c)
  fi
fi
if [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]]; then
  profiles+=(md-cluster)
  export MDSVR_CONFIG_NAME=MDSvrA
  if [[ "${MD_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    profiles+=(md-cluster-c)
  fi
fi
if [[ "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
  profiles+=(trade-cluster)
  export TRADESVR_CONFIG_NAME=TradeSvrA
else
  export TRADESVR_CONFIG_NAME=TradeSvr
fi
export COMPOSE_PROFILES="$(IFS=,; printf '%s' "${profiles[*]}")"

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" "$@"
}

# DEPLOY_ROOT lives inside the Colima VM on macOS. Read generated runtime
# configuration through a running container when the host cannot see it.
runtime_cat() {
  local path="$1" rel
  if [[ -r "${path}" ]]; then
    cat "${path}"
    return
  fi
  rel="${path#${DEPLOY_ROOT}}"
  docker exec dc-saas-gateway cat "/srv/dc${rel}"
}

runtime_grep() {
  local pattern="$1" path="$2"
  runtime_cat "${path}" | grep -Fq -- "${pattern}"
}

gateway_client_config="${DEPLOY_ROOT}/control/overrides/GW/config/spring-gw-client.xml"
if [[ ! -r "${gateway_client_config}" ]]; then
  runtime_tmp="$(mktemp -d)"
  trap 'rm -rf "${runtime_tmp}"' EXIT
  docker cp dc-saas-gateway:/srv/dc/control "${runtime_tmp}/control" >/dev/null
  DEPLOY_ROOT="${runtime_tmp}"
  gateway_client_config="${DEPLOY_ROOT}/control/overrides/GW/config/spring-gw-client.xml"
fi
[[ -r "${gateway_client_config}" ]] ||
  die "Generated GW client configuration is missing: ${gateway_client_config}."
grep -Fq 'dc.md.orderbook.**' "${gateway_client_config}" ||
  die "GW is not subscribed to tenant order-book broadcasts (dc.md.orderbook.**)."

grep -Fq 'openApiIngressSecurityCheck' "${gateway_client_config}" ||
  die "GW Open API ingress policy is not enabled."
grep -Fq 'com.app.gw.security.OpenApiIngressSecurityCheck' "${gateway_client_config}" ||
  die "GW Open API ingress policy bean is missing."
grep -Fq 'com.app.gw.security.SaasGWProxy' "${gateway_client_config}" ||
  die "GW SaaS proxy is not enforcing signed /api boundary semantics."
grep -Fq '<ref bean="apiKeyService"/><ref bean="openApiIngressSecurityCheck"/>' "${gateway_client_config}" ||
  die "GW Open API ingress policy is not subscribed to API-key policy updates."
grep -Fq 'com.app.gw.security.OpenApiRateLimitSecurityCheck' "${gateway_client_config}" ||
  die "GW Open API rate-limit profile policy bean is missing."
grep -Fq '<property name="securityChecks"><list><ref bean="openApiIngressSecurityCheck"/><ref bean="openApiRateLimitSecurityCheck"/><ref bean="sqlInjSecurityCheck"/></list></property>' "${gateway_client_config}" ||
  die "GW Open API rate-limit profile policy is not active in request security checks."
grep -Fq '<property name="filterTopics"><list><ref bean="apiKeyService"/><ref bean="openApiIngressSecurityCheck"/><ref bean="openApiRateLimitSecurityCheck"/></list></property>' "${gateway_client_config}" ||
  die "GW Open API rate-limit profile policy is not subscribed to LoginSvr session updates."
grep -Fq '<property name="openApiRateLimitSecurityCheck" ref="openApiRateLimitSecurityCheck"/>' "${gateway_client_config}" ||
  die "GW Open API response sanitizer cannot resolve API/TenantAPI Session policy."
grep -Fq '<property name="traderStandardQps" value="100"/>' "${gateway_client_config}" &&
grep -Fq '<property name="traderStandardBurst" value="30"/>' "${gateway_client_config}" &&
grep -Fq '<property name="tenantStandardQps" value="20"/>' "${gateway_client_config}" &&
grep -Fq '<property name="tenantStandardBurst" value="10"/>' "${gateway_client_config}" ||
  die "GW Open API rate-limit profile values are not the SaaS baseline (Trader 100/30, Tenant 20/10)."

login_config="${DEPLOY_ROOT}/control/overrides/LoginSvr/config/application.properties"
[[ -r "${login_config}" ]] ||
  die "Generated LoginSvr configuration is missing: ${login_config}."
grep -Fqx 'server.address=127.0.0.1' "${login_config}" ||
  die "LoginSvr REST endpoint must bind to 127.0.0.1; external API traffic must enter through GW."

services="$(compose config --services)"
if grep -Eiq '(^|_)(quant|ind|sim|batch|customind)' <<<"${services}"; then
  die "Quantitative-trading services leaked into the SaaS compose model."
fi

expected_containers=(
  dc-saas-mysql dc-saas-clickhouse dc-saas-zookeeper dc-saas-gateway
  dc-saas-loginsvr dc-saas-mdsvr dc-saas-apssvr dc-saas-ordersvr
  dc-saas-tradesvr dc-saas-liqsvr dc-saas-managersvr dc-saas-adminsvr
  dc-saas-robotsvr dc-saas-trade-web dc-saas-tenant-web dc-saas-platform-web
)
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
  expected_containers+=(dc-saas-ordersvr-b)
  if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    expected_containers+=(dc-saas-ordersvr-c)
  fi
fi
if [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]]; then
  expected_containers+=(dc-saas-mdsvr-b)
  if [[ "${MD_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    expected_containers+=(dc-saas-mdsvr-c)
  fi
fi
if [[ "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
  expected_containers+=(dc-saas-tradesvr-b)
fi
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" || "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
  expected_containers+=(dc-saas-projectionsvr)
fi

for container in "${expected_containers[@]}"; do
  state="$(docker inspect --format '{{.State.Status}}' "${container}" 2>/dev/null || true)"
  [[ "${state}" == "running" ]] || {
    docker logs --tail 80 "${container}" >&2 || true
    die "${container} is not running (state=${state:-missing})."
  }
done

for container in dc-saas-mysql dc-saas-clickhouse dc-saas-zookeeper dc-saas-trade-web dc-saas-tenant-web dc-saas-platform-web; do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${container}" 2>/dev/null || true)"
  [[ "${health}" == "healthy" ]] || die "${container} health is ${health:-missing}."
done

required_ports=(
  "${MYSQL_PORT}" "${CLICKHOUSE_HTTP_PORT}" "${CLICKHOUSE_NATIVE_PORT}"
  "${ZOOKEEPER_PORT}" "${GW_TCP_PORT}" "${GW_WEBSOCKET_PORT}" "${GW_HTTP_PORT}"
  "${LOGINSVR_HTTP_PORT}" "${LOGINSVR_GW_PORT}" "${MDSVR_GW_PORT}" "${APSSVR_GW_PORT}"
  "${ORDERSVR_GW_PORT}" "${TRADESVR_GW_PORT}" "${LIQSVR_GW_PORT}"
  "${MANAGERSVR_GW_PORT}" "${ADMINSVR_GW_PORT}" "${WEB_LISTEN_PORT}" "18092" "18090"
)
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" || "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
  required_ports+=("${PROJECTIONSVR_GW_PORT:-33042}")
fi
if [[ "${ORDER_CLUSTER_ENABLED:-false}" == "true" ]]; then
  required_ports+=("${ORDERSVR_B_GW_PORT}" "${ORDERSVR_A_REPLICATION_PORT}" "${ORDERSVR_B_REPLICATION_PORT}")
  grep -Fqx 'ProtoVersion=2' "${DEPLOY_ROOT}/control/ATSConfig.ini" ||
    die "OrderSvr partition routing requires ProtoVersion=2."
  grep -Fq 'LBConfig.OrderSvr=Partition' "${DEPLOY_ROOT}/control/ATSConfig.ini" ||
    die "OrderSvr partition load balancing is not enabled in ATSConfig.ini."
  grep -Fq 'serverKey=SERVER.OrderSvrA' \
    "${DEPLOY_ROOT}/control/overrides/OrderSvrA/config/application.properties" ||
    die "OrderSvrA cluster configuration is missing."
  grep -Fq 'serverKey=SERVER.OrderSvrB' \
    "${DEPLOY_ROOT}/control/overrides/OrderSvrB/config/application.properties" ||
    die "OrderSvrB cluster configuration is missing."
  grep -Fq 'projection.binary.enabled=true' \
    "${DEPLOY_ROOT}/control/overrides/ProjectionSvr/config/application.properties" ||
    die "ProjectionSvr Order committed-event consumer must be enabled."
  if [[ "${ORDER_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    required_ports+=("${ORDERSVR_C_GW_PORT}" "${ORDERSVR_C_REPLICATION_PORT}")
    grep -Fq 'serverKey=SERVER.OrderSvrC' \
      "${DEPLOY_ROOT}/control/overrides/OrderSvrC/config/application.properties" ||
      die "OrderSvrC cluster configuration is missing."
  fi
fi
if [[ "${MD_CLUSTER_ENABLED:-false}" == "true" ]]; then
  required_ports+=("${MDSVR_B_GW_PORT}")
  grep -Fqx 'ProtoVersion=2' "${DEPLOY_ROOT}/control/ATSConfig.ini" ||
    die "MDSvr partition routing requires ProtoVersion=2."
  grep -Fq 'LBConfig.MDSvr=Partition' "${DEPLOY_ROOT}/control/ATSConfig.ini" ||
    die "MDSvr partition load balancing is not enabled in ATSConfig.ini."
  grep -Fq 'serverKey=SERVER.MDSvrA' \
    "${DEPLOY_ROOT}/control/overrides/MDSvrA/config/application.properties" ||
    die "MDSvrA cluster configuration is missing."
  grep -Fq 'serverKey=SERVER.MDSvrB' \
    "${DEPLOY_ROOT}/control/overrides/MDSvrB/config/application.properties" ||
    die "MDSvrB cluster configuration is missing."
  if [[ "${MD_CLUSTER_C_ENABLED:-false}" == "true" ]]; then
    required_ports+=("${MDSVR_C_GW_PORT}")
    grep -Fq 'serverKey=SERVER.MDSvrC' \
      "${DEPLOY_ROOT}/control/overrides/MDSvrC/config/application.properties" ||
      die "MDSvrC cluster configuration is missing."
  fi
fi
if [[ "${TRADE_CLUSTER_ENABLED:-false}" == "true" ]]; then
  required_ports+=("${TRADESVR_B_GW_PORT}")
  grep -Fqx 'ProtoVersion=2' "${DEPLOY_ROOT}/control/ATSConfig.ini" ||
    die "TradeSvr partition routing requires ProtoVersion=2."
  grep -Fq 'LBConfig.TradeSvr=Partition' "${DEPLOY_ROOT}/control/ATSConfig.ini" ||
    die "TradeSvr partition load balancing is not enabled in ATSConfig.ini."
  grep -Fq 'serverKey=SERVER.TradeSvrA' \
    "${DEPLOY_ROOT}/control/overrides/TradeSvrA/config/application.properties" ||
    die "TradeSvrA cluster configuration is missing."
  grep -Fq 'serverKey=SERVER.TradeSvrB' \
    "${DEPLOY_ROOT}/control/overrides/TradeSvrB/config/application.properties" ||
    die "TradeSvrB cluster configuration is missing."
  grep -Fq 'trade.node.businessEnabled=true' \
    "${DEPLOY_ROOT}/control/overrides/TradeSvrB/config/application.properties" ||
    die "TradeSvrB hot runtime must be enabled; partition readiness fencing controls writes."
  grep -Fq 'trade.cluster.lifecycle.enabled=true' \
    "${DEPLOY_ROOT}/control/overrides/TradeSvrB/config/application.properties" ||
    die "TradeSvrB recovery lifecycle must be enabled."
  grep -Fq 'trade.cluster.recovery.authoritative=true' \
    "${DEPLOY_ROOT}/control/overrides/TradeSvrB/config/application.properties" ||
    die "TradeSvrB authoritative recovery must be enabled."
  grep -Fq 'projection.trade.binary.enabled=true' \
    "${DEPLOY_ROOT}/control/overrides/ProjectionSvr/config/application.properties" ||
    die "ProjectionSvr Trade committed-event consumer must be enabled."
fi

if command -v ss >/dev/null 2>&1; then
  listening="$(ss -lnt | awk 'NR > 1 {print $4}')"
else
  listening="$(docker ps --format '{{.Ports}}' | tr ',' '\n' | grep -oE '127\.0\.0\.1:[0-9]+|0\.0\.0\.0:[0-9]+|\[::\]:[0-9]+' || true)"
fi
for port in "${required_ports[@]}"; do
  if command -v ss >/dev/null 2>&1; then
    grep -Eq "[:.]${port}$" <<<"${listening}" || die "Expected port ${port} is not listening."
  else
    nc -z 127.0.0.1 "${port}" >/dev/null 2>&1 || die "Expected port ${port} is not listening."
  fi
done

for port in "${MYSQL_PORT}" "${CLICKHOUSE_HTTP_PORT}" "${CLICKHOUSE_NATIVE_PORT}" "${ZOOKEEPER_PORT}"; do
  if command -v ss >/dev/null 2>&1; then
    while IFS= read -r endpoint; do
      case "${endpoint}" in
        "127.0.0.1:${port}"|"[::1]:${port}"|"[::ffff:127.0.0.1]:${port}") ;;
        *) die "Infrastructure port ${port} is exposed on non-loopback endpoint ${endpoint}." ;;
      esac
    done < <(ss -lntH "sport = :${port}" | awk '{print $4}')
  else
    docker ps --format '{{.Ports}}' | grep -E "(^|, )0\.0\.0\.0:${port}->|(^|, )\[::\]:${port}->" >/dev/null &&
      die "Infrastructure port ${port} is exposed on a non-loopback Docker endpoint." || true
  fi
done

mysql_table_count="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dc';"
)"
[[ "${mysql_table_count}" =~ ^[0-9]+$ ]] || die "Could not count MySQL dc tables."
(( mysql_table_count >= 20 )) || die "MySQL dc schema is incomplete: ${mysql_table_count} tables."

mysql_location_columns="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc' AND column_name='location';"
)"
(( mysql_location_columns >= 10 )) ||
  die "MySQL location isolation columns are incomplete: ${mysql_location_columns}."

robot_schema_count="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dc' AND table_name='dc_robot_hedge_execution';"
)"
[[ "${robot_schema_count}" == "1" ]] || die "Robot hedge execution journal is missing."

robot_runtime_columns="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc' AND table_name='dc_tenant_robot' AND column_name IN ('quote_source','runtime_owner','runtime_lease_until','last_error_code','last_error_message','last_reference_price','open_order_count');"
)"
[[ "${robot_runtime_columns}" == "7" ]] || die "Robot runtime schema is incomplete: ${robot_runtime_columns}/7 columns."

open_api_key_policy_columns="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse     "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc' AND table_name='dc_users_api' AND column_name IN ('permissions','ip_whitelist','expires_at','rate_limit_profile','label','last_used_time');"
)"
[[ "${open_api_key_policy_columns}" == "6" ]] ||
  die "Crypto Open API key policy schema is incomplete: ${open_api_key_policy_columns}/6 columns."

open_api_session_context_columns="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse     "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc' AND table_name='dc_users_session' AND column_name IN ('api_key_type','permissions','rate_limit_profile');"
)"
[[ "${open_api_session_context_columns}" == "3" ]] ||
  die "Open API session context schema is incomplete: ${open_api_session_context_columns}/3 columns."

robot_runtime_identity_count="$(
  docker exec -e MYSQL_PWD="${MYSQL_PASSWORD}" dc-saas-mysql mysql -u"${MYSQL_USERNAME}" -Nse \
    "SELECT COUNT(*) FROM dc.dc_users_api WHERE location='${ROBOT_RUNTIME_LOCATION}' AND user_id='${ROBOT_RUNTIME_USER_ID}' AND api_key='${ROBOT_RUNTIME_API_KEY}' AND enable='1' AND secret_key IS NOT NULL;"
)"
[[ "${robot_runtime_identity_count}" == "1" ]] || die "Dedicated Robot runtime API identity is missing or disabled."

clickhouse_location="$(
  docker exec dc-saas-clickhouse clickhouse-client --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" --password "${CLICKHOUSE_PASSWORD}" --query "SELECT count() FROM system.columns WHERE database='dc' AND table='kline' AND name='location'"
)"
[[ "${clickhouse_location}" == "1" ]] || die "ClickHouse kline.location is missing."

clickhouse_view="$(
  docker exec dc-saas-clickhouse clickhouse-client --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" --password "${CLICKHOUSE_PASSWORD}" --query "SELECT count() FROM system.tables WHERE database='dc' AND name='kline_view'"
)"
[[ "${clickhouse_view}" == "1" ]] || die "ClickHouse kline_view is missing."

docker exec dc-saas-trade-web wget -qO- "http://127.0.0.1:${WEB_LISTEN_PORT}/healthz" | grep -q '^ok$' ||
  die "dc-trade-web health endpoint failed."
docker exec dc-saas-trade-web wget -qO- "http://127.0.0.1:${WEB_LISTEN_PORT}/" | grep -qi '<title>Trade</title>' ||
  die "dc-trade-web index page is not the trade application."

wait_for_gateway_route() {
  local server="$1" response start
  start="$(date +%s)"
  while true; do
    response="$(docker exec dc-saas-trade-web wget -qO- \
      --header='Content-Type: application/json' \
      --post-data="{\"serverName\":\"${server}\",\"method\":\"getSymbolConfig\",\"content\":{\"SecurityID\":\"BTCUSDT\"}}" \
      "http://127.0.0.1:${WEB_LISTEN_PORT}/httpapi/" 2>/dev/null || true)"
    if [[ -n "${response}" && "${response}" != *"SERVER.${server} is not Online"* ]]; then
      log "GW route ${server}: online"
      return 0
    fi
    if (( $(date +%s) - start >= 120 )); then
      die "GW route ${server} did not become online after 120 seconds."
    fi
    sleep 3
  done
}

# TradeSvr exposes authenticated configuration endpoints by its instance name,
# while balance/funding compatibility endpoints use its TDSvr service alias.
# Both routes converge asynchronously after a rolling container/GW update.
wait_for_gateway_route TradeSvr
wait_for_gateway_route TDSvr

log "SaaS-only compose model verified."
log "All ${#expected_containers[@]} expected containers are running; MySQL tables=${mysql_table_count}, location columns=${mysql_location_columns}."
log "MySQL, ClickHouse, and ZooKeeper are restricted to loopback interfaces."
log "ClickHouse kline is location-aware and dc-trade-web is healthy."
