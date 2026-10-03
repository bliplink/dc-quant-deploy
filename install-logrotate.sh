#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
CONFIG_FILE="/etc/logrotate.d/dc-quant-runtime"

[[ "${EUID}" -eq 0 ]] || {
  echo "Run this installer with sudo." >&2
  exit 1
}
[[ -f "${ENV_FILE}" ]] || {
  echo "Missing environment file: ${ENV_FILE}" >&2
  exit 1
}

# shellcheck disable=SC1090
set -a && . "${ENV_FILE}" && set +a
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
[[ "${DEPLOY_ROOT}" == /* ]] || {
  echo "DEPLOY_ROOT must be an absolute path." >&2
  exit 1
}

mkdir -p "${DEPLOY_ROOT}/log"

temporary_file="$(mktemp)"
trap 'rm -f "${temporary_file}"' EXIT
cat > "${temporary_file}" <<EOF
"${DEPLOY_ROOT}/log/"*.log {
    daily
    maxsize 100M
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
}
EOF

install -m 0644 "${temporary_file}" "${CONFIG_FILE}"
logrotate -d "${CONFIG_FILE}" >/dev/null 2>&1

echo "Installed application log rotation at ${CONFIG_FILE}."
