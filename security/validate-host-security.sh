#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"

fail() {
  echo "security validation failed: $*" >&2
  exit 1
}

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command $1"
}

load_env() {
  [[ -f "${ENV_FILE}" ]] || fail "missing ${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a

  PUBLIC_SSH_PORT="${PUBLIC_SSH_PORT:-22}"
  CLICKHOUSE_PUBLIC_HTTP_PORT="${CLICKHOUSE_PUBLIC_HTTP_PORT:-28123}"
  CLICKHOUSE_PUBLIC_ACCESS="${CLICKHOUSE_PUBLIC_ACCESS:-true}"
  CLICKHOUSE_USERNAME="${CLICKHOUSE_USERNAME:-default}"
  CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-}"
  CLICKHOUSE_HOST="${CLICKHOUSE_HOST:-127.0.0.1}"
  SERVICE_HOST="${SERVICE_HOST:-127.0.0.1}"
}

is_local_clickhouse() {
  case "${CLICKHOUSE_HOST}" in
    127.0.0.1|localhost|0.0.0.0|"${SERVICE_HOST}")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

port_open() {
  local host="$1"
  local port="$2"
  bash -c "exec 3<>/dev/tcp/${host}/${port}" >/dev/null 2>&1
}

http_head_contains() {
  local url="$1"
  local pattern="$2"
  curl -sS -I --max-time 5 "${url}" | grep -Eiq "${pattern}"
}

validate_web() {
  docker ps --filter 'name=^/dc-web$' --format '{{.Names}}' | grep -qx dc-web || fail "dc-web is not running"

  local mounts
  mounts="$(docker inspect dc-web --format '{{range .Mounts}}{{.Source}}->{{.Destination}} {{end}}')"
  if grep -q '/etc/nginx/conf.d/default.conf' <<<"${mounts}"; then
    fail "dc-web still has an nginx config bind mount"
  fi

  docker exec dc-web nginx -t >/dev/null 2>&1 || fail "dc-web nginx -t failed"
  curl -fsS --max-time 5 http://127.0.0.1/web/ >/dev/null || fail "/web/ is not reachable"
  curl -fsS --max-time 5 http://127.0.0.1/healthz | grep -qx ok || fail "/healthz is not ok"

  http_head_contains http://127.0.0.1/web/ '^Server: nginx$' || fail "web Server header still exposes version"
  http_head_contains http://127.0.0.1/web/ '^X-Content-Type-Options: nosniff' || fail "web missing nosniff header"
  http_head_contains http://127.0.0.1/web/ '^X-Frame-Options: SAMEORIGIN' || fail "web missing frame header"

  for path in /.env /.git/config /server-status /actuator /api-docs /swagger-ui/ /phpmyadmin/ /wp-login.php /xmlrpc.php /cgi-bin/test; do
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1${path}" || true)"
    [[ "${code}" == "000" ]] || fail "scan path ${path} returned ${code}, expected empty response"
  done
}

validate_clickhouse_proxy() {
  if [[ "${CLICKHOUSE_PUBLIC_ACCESS}" != "true" ]]; then
    return 0
  fi

  if ! is_local_clickhouse; then
    return 0
  fi

  systemctl is-active clickhouse-http-proxy.service >/dev/null || fail "clickhouse-http-proxy.service is not active"
  port_open 127.0.0.1 "${CLICKHOUSE_PUBLIC_HTTP_PORT}" || fail "ClickHouse public proxy port is not open locally"

  if [[ -n "${CLICKHOUSE_PASSWORD}" ]]; then
    curl -fsS --max-time 5 \
      "http://127.0.0.1:${CLICKHOUSE_PUBLIC_HTTP_PORT}/?user=${CLICKHOUSE_USERNAME}&password=${CLICKHOUSE_PASSWORD}&query=SELECT%201" \
      | grep -qx "1" || fail "ClickHouse public proxy query failed"
  else
    curl -fsS --max-time 5 \
      "http://127.0.0.1:${CLICKHOUSE_PUBLIC_HTTP_PORT}/?user=${CLICKHOUSE_USERNAME}&query=SELECT%201" \
      | grep -qx "1" || fail "ClickHouse public proxy query failed"
  fi
}

validate_firewall() {
  ufw status | grep -q '^Status: active' || fail "ufw is not active"
  port_open 127.0.0.1 "${PUBLIC_SSH_PORT}" || fail "SSH port ${PUBLIC_SSH_PORT} is not open locally"
  port_open 127.0.0.1 80 || fail "web port 80 is not open locally"

  for port in 8123 9000 2181 30028 30035 30042 30044 30045 30046; do
    if ufw status numbered | grep -Eq "[[:space:]]${port}/tcp[[:space:]]+ALLOW"; then
      fail "ufw explicitly allows internal port ${port}"
    fi
  done
}

validate_host_nginx() {
  if systemctl is-active nginx >/dev/null 2>&1; then
    fail "host nginx is active; web should be served by dc-web container"
  fi
}

main() {
  check_cmd docker
  check_cmd curl
  check_cmd ufw
  check_cmd systemctl
  load_env
  validate_web
  validate_clickhouse_proxy
  validate_firewall
  validate_host_nginx
  echo "Host security validation passed."
}

main "$@"
