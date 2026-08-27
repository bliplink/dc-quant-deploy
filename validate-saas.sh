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

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${SCRIPT_DIR}/compose.yaml" "$@"
}

services="$(compose config --services)"
if grep -Eiq '(^|_)(quant|ind|sim|batch|customind)' <<<"${services}"; then
  die "Quantitative-trading services leaked into the SaaS compose model."
fi

expected_containers=(
  dc-saas-mysql dc-saas-clickhouse dc-saas-zookeeper dc-saas-gateway
  dc-saas-loginsvr dc-saas-mdsvr dc-saas-apssvr dc-saas-ordersvr
  dc-saas-tradesvr dc-saas-liqsvr dc-saas-managersvr dc-saas-adminsvr
  dc-saas-trade-web
)

for container in "${expected_containers[@]}"; do
  state="$(docker inspect --format '{{.State.Status}}' "${container}" 2>/dev/null || true)"
  [[ "${state}" == "running" ]] || {
    docker logs --tail 80 "${container}" >&2 || true
    die "${container} is not running (state=${state:-missing})."
  }
done

for container in dc-saas-mysql dc-saas-clickhouse dc-saas-trade-web; do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${container}" 2>/dev/null || true)"
  [[ "${health}" == "healthy" ]] || die "${container} health is ${health:-missing}."
done

required_ports=(
  "${MYSQL_PORT}" "${CLICKHOUSE_HTTP_PORT}" "${CLICKHOUSE_NATIVE_PORT}"
  "${ZOOKEEPER_PORT}" "${GW_TCP_PORT}" "${GW_WEBSOCKET_PORT}" "${GW_HTTP_PORT}"
  "${LOGINSVR_HTTP_PORT}" "${LOGINSVR_GW_PORT}" "${MDSVR_GW_PORT}" "${APSSVR_GW_PORT}"
  "${ORDERSVR_GW_PORT}" "${TRADESVR_GW_PORT}" "${LIQSVR_GW_PORT}"
  "${MANAGERSVR_GW_PORT}" "${ADMINSVR_GW_PORT}" "${WEB_LISTEN_PORT}"
)

listening="$(ss -lnt | awk 'NR > 1 {print $4}')"
for port in "${required_ports[@]}"; do
  grep -Eq "[:.]${port}$" <<<"${listening}" || die "Expected port ${port} is not listening."
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

clickhouse_location="$(
  docker exec dc-saas-clickhouse clickhouse-client --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" --password "${CLICKHOUSE_PASSWORD}" --query "SELECT count() FROM system.columns WHERE database='dc' AND table='kline' AND name='location'"
)"
[[ "${clickhouse_location}" == "1" ]] || die "ClickHouse kline.location is missing."

clickhouse_view="$(
  docker exec dc-saas-clickhouse clickhouse-client --port "${CLICKHOUSE_NATIVE_PORT}" --user "${CLICKHOUSE_USERNAME}" --password "${CLICKHOUSE_PASSWORD}" --query "SELECT count() FROM system.tables WHERE database='dc' AND name='kline_view'"
)"
[[ "${clickhouse_view}" == "1" ]] || die "ClickHouse kline_view is missing."

curl -fsS "http://127.0.0.1:${WEB_LISTEN_PORT}/healthz" | grep -q '^ok$' ||
  die "dc-trade-web health endpoint failed."
curl -fsS "http://127.0.0.1:${WEB_LISTEN_PORT}/" | grep -qi '<title>Trade</title>' ||
  die "dc-trade-web index page is not the trade application."

log "SaaS-only compose model verified."
log "All 13 containers are running; MySQL tables=${mysql_table_count}, location columns=${mysql_location_columns}."
log "ClickHouse kline is location-aware and dc-trade-web is healthy."
