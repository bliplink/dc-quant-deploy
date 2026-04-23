#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
DRY_RUN=false
BACKUP_DIR=""
ROLLBACK_UNIT=""
CLICKHOUSE_PROXY_ENABLED=false

usage() {
  cat <<'USAGE'
Usage:
  ./security/harden-host.sh [--dry-run]

Harden the host after DC services are already deployed.

This script:
  - reads .env.prod
  - backs up firewall and runtime status
  - disables the host nginx service
  - optionally exposes ClickHouse HTTP through a local proxy port
  - enables UFW with a minimal allowlist
  - creates a short automatic firewall rollback timer before changing UFW

It does not start, stop, or recreate DC business containers.
USAGE
}

log() {
  printf '%s\n' "$*"
}

run() {
  if "${DRY_RUN}"; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

require_root() {
  if "${DRY_RUN}"; then
    return 0
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must be run as root." >&2
    exit 1
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

load_env() {
  [[ -f "${ENV_FILE}" ]] || {
    echo "Missing ${ENV_FILE}. Deploy first or create .env.prod." >&2
    exit 1
  }
  # shellcheck disable=SC1090
  set -a && . "${ENV_FILE}" && set +a

  PUBLIC_SSH_PORT="${PUBLIC_SSH_PORT:-22}"
  CLICKHOUSE_PUBLIC_HTTP_PORT="${CLICKHOUSE_PUBLIC_HTTP_PORT:-28123}"
  CLICKHOUSE_PUBLIC_ACCESS="${CLICKHOUSE_PUBLIC_ACCESS:-true}"
  ALLOW_GW_PUBLIC="${ALLOW_GW_PUBLIC:-true}"
  SECURITY_AUTO_ROLLBACK_MINUTES="${SECURITY_AUTO_ROLLBACK_MINUTES:-5}"
  CLICKHOUSE_HOST="${CLICKHOUSE_HOST:-127.0.0.1}"
  CLICKHOUSE_HTTP_PORT="${CLICKHOUSE_HTTP_PORT:-8123}"
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

prepare_backup() {
  local ts
  ts="$(date '+%Y%m%d%H%M%S')"
  BACKUP_DIR="${DEPLOY_ROOT:-/opt/dc-runtime}/backup/host-security-${ts}"

  if "${DRY_RUN}"; then
    log "[dry-run] backup directory would be ${BACKUP_DIR}"
    return 0
  fi

  mkdir -p "${BACKUP_DIR}"
  chmod 700 "${BACKUP_DIR}"

  iptables-save > "${BACKUP_DIR}/iptables-save.bak" 2>/dev/null || true
  ufw status verbose > "${BACKUP_DIR}/ufw-status.before" 2>/dev/null || true
  docker ps --format '{{.Names}} {{.Status}} {{.Image}}' > "${BACKUP_DIR}/docker-ps.before" 2>/dev/null || true
  ss -ltnp > "${BACKUP_DIR}/ss-ltnp.before" 2>/dev/null || true
  cp -a "${ENV_FILE}" "${BACKUP_DIR}/env.prod.bak"

  cat > "${BACKUP_DIR}/rollback-firewall.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ufw disable || true
systemctl stop clickhouse-http-proxy.service >/dev/null 2>&1 || true
systemctl disable clickhouse-http-proxy.service >/dev/null 2>&1 || true
EOF
  chmod 700 "${BACKUP_DIR}/rollback-firewall.sh"
  log "Backup saved to ${BACKUP_DIR}"
}

schedule_rollback() {
  ROLLBACK_UNIT="dc-host-security-rollback-$(date '+%Y%m%d%H%M%S')"
  run systemctl stop "${ROLLBACK_UNIT}.timer" "${ROLLBACK_UNIT}.service" >/dev/null 2>&1 || true
  run systemctl reset-failed "${ROLLBACK_UNIT}.timer" "${ROLLBACK_UNIT}.service" >/dev/null 2>&1 || true
  run systemd-run --unit "${ROLLBACK_UNIT}" --on-active="${SECURITY_AUTO_ROLLBACK_MINUTES}m" "${BACKUP_DIR}/rollback-firewall.sh"
  log "Automatic rollback timer: ${ROLLBACK_UNIT}.timer (${SECURITY_AUTO_ROLLBACK_MINUTES} minutes)"
}

cancel_rollback() {
  [[ -n "${ROLLBACK_UNIT}" ]] || return 0
  run systemctl stop "${ROLLBACK_UNIT}.timer" "${ROLLBACK_UNIT}.service" >/dev/null 2>&1 || true
  run systemctl reset-failed "${ROLLBACK_UNIT}.timer" "${ROLLBACK_UNIT}.service" >/dev/null 2>&1 || true
  log "Automatic rollback timer cancelled."
}

install_clickhouse_proxy() {
  CLICKHOUSE_PROXY_ENABLED=false

  if [[ "${CLICKHOUSE_PUBLIC_ACCESS}" != "true" ]]; then
    log "ClickHouse public proxy disabled by CLICKHOUSE_PUBLIC_ACCESS=${CLICKHOUSE_PUBLIC_ACCESS}."
    run systemctl stop clickhouse-http-proxy.service >/dev/null 2>&1 || true
    run systemctl disable clickhouse-http-proxy.service >/dev/null 2>&1 || true
    return 0
  fi

  if ! is_local_clickhouse; then
    log "ClickHouse host is ${CLICKHOUSE_HOST}; skip local public proxy because ClickHouse is not on this host."
    run systemctl stop clickhouse-http-proxy.service >/dev/null 2>&1 || true
    run systemctl disable clickhouse-http-proxy.service >/dev/null 2>&1 || true
    return 0
  fi

  CLICKHOUSE_PROXY_ENABLED=true

  if "${DRY_RUN}"; then
    log "[dry-run] install clickhouse-http-proxy.service on port ${CLICKHOUSE_PUBLIC_HTTP_PORT} -> 127.0.0.1:${CLICKHOUSE_HTTP_PORT}"
    return 0
  fi

  cat > /usr/local/sbin/clickhouse-http-proxy.py <<PY
#!/usr/bin/env python3
import select
import socket
import threading

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int("${CLICKHOUSE_PUBLIC_HTTP_PORT}")
TARGET_HOST = "127.0.0.1"
TARGET_PORT = int("${CLICKHOUSE_HTTP_PORT}")
BUFFER_SIZE = 65536

def pipe(client_sock, client_addr):
    upstream = None
    try:
        upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=10)
        client_sock.setblocking(False)
        upstream.setblocking(False)
        sockets = [client_sock, upstream]
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 300)
            if exceptional or not readable:
                break
            for src in readable:
                dst = upstream if src is client_sock else client_sock
                try:
                    data = src.recv(BUFFER_SIZE)
                except BlockingIOError:
                    continue
                if not data:
                    return
                dst.sendall(data)
    finally:
        for sock in (client_sock, upstream):
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(256)
    while True:
        client_sock, client_addr = server.accept()
        threading.Thread(target=pipe, args=(client_sock, client_addr), daemon=True).start()

if __name__ == "__main__":
    main()
PY
  chmod 755 /usr/local/sbin/clickhouse-http-proxy.py

  cat > /etc/systemd/system/clickhouse-http-proxy.service <<'UNIT'
[Unit]
Description=ClickHouse HTTP public port proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/sbin/clickhouse-http-proxy.py
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable --now clickhouse-http-proxy.service
}

configure_ufw() {
  schedule_rollback

  run ufw --force reset
  run ufw default deny incoming
  run ufw default allow outgoing
  run ufw allow in on lo comment 'loopback'
  run ufw allow "${PUBLIC_SSH_PORT}/tcp" comment 'SSH'
  run ufw allow 80/tcp comment 'Web'

  if [[ "${ALLOW_GW_PUBLIC}" == "true" ]]; then
    run ufw allow 3000/tcp comment 'GW'
    run ufw allow 3001/tcp comment 'GW'
    run ufw allow 3002/tcp comment 'GW MCP'
  fi

  if [[ "${CLICKHOUSE_PROXY_ENABLED}" == "true" ]]; then
    run ufw allow "${CLICKHOUSE_PUBLIC_HTTP_PORT}/tcp" comment 'ClickHouse external HTTP proxy'
  fi

  run ufw allow from 127.0.0.1 comment 'loopback source'
  run ufw allow from "${SERVICE_HOST:-127.0.0.1}" comment 'service host'
  run ufw --force enable
}

disable_host_nginx() {
  run systemctl disable --now nginx >/dev/null 2>&1 || true
}

validate_or_rollback() {
  if "${DRY_RUN}"; then
    log "[dry-run] skip validation and rollback timer cancellation."
    return 0
  fi

  if "${SCRIPT_DIR}/validate-host-security.sh"; then
    cancel_rollback
    ufw status verbose > "${BACKUP_DIR}/ufw-status.after" 2>/dev/null || true
    ss -ltnp > "${BACKUP_DIR}/ss-ltnp.after" 2>/dev/null || true
    docker ps --format '{{.Names}} {{.Status}} {{.Image}}' > "${BACKUP_DIR}/docker-ps.after" 2>/dev/null || true
    log "Host security hardening completed."
  else
    echo "Security validation failed. Running firewall rollback." >&2
    "${BACKUP_DIR}/rollback-firewall.sh" || true
    exit 1
  fi
}

main() {
  case "${1:-}" in
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    "")
      ;;
    *)
      echo "Unexpected argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac

  require_root
  require_cmd docker
  require_cmd ss
  require_cmd ufw
  require_cmd systemctl
  require_cmd python3
  load_env
  prepare_backup
  log "Allowlist: SSH ${PUBLIC_SSH_PORT}, Web 80, GW public ${ALLOW_GW_PUBLIC}, ClickHouse public ${CLICKHOUSE_PUBLIC_ACCESS}:${CLICKHOUSE_PUBLIC_HTTP_PORT}"
  disable_host_nginx
  install_clickhouse_proxy
  configure_ufw
  validate_or_rollback
}

main "$@"
