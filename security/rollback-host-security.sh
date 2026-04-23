#!/usr/bin/env bash
set -euo pipefail

RESTORE_HOST_NGINX=false

usage() {
  cat <<'USAGE'
Usage:
  ./security/rollback-host-security.sh [--restore-host-nginx]

Rollback host-level security hardening.

This script:
  - disables UFW
  - stops and disables clickhouse-http-proxy.service
  - keeps DC business containers running
  - restores host nginx only when --restore-host-nginx is provided
USAGE
}

case "${1:-}" in
  --restore-host-nginx)
    RESTORE_HOST_NGINX=true
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

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root." >&2
  exit 1
fi

ufw disable || true
systemctl stop clickhouse-http-proxy.service >/dev/null 2>&1 || true
systemctl disable clickhouse-http-proxy.service >/dev/null 2>&1 || true

if "${RESTORE_HOST_NGINX}"; then
  systemctl enable --now nginx || true
fi

echo "Host security rollback completed. DC containers were not changed."
