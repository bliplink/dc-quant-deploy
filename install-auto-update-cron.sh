#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
UPDATE_SCRIPT="${SCRIPT_DIR}/auto-update-saas.sh"
BEGIN_MARKER="# BEGIN DC SAAS AUTO UPDATE"
END_MARKER="# END DC SAAS AUTO UPDATE"
LOGROTATE_FILE="/etc/logrotate.d/dc-saas-auto-update"

INTERVAL_MINUTES=""
REMOVE="false"

usage() {
  cat <<'EOF'
Usage: sudo ./install-auto-update-cron.sh [--interval-minutes N] [--remove]

Installs an idempotent root cron entry for the standalone SaaS stack. The
default interval is five minutes. --remove deletes only the managed cron block
and its logrotate policy.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --interval-minutes)
      shift
      [[ "$#" -gt 0 ]] || { usage >&2; exit 1; }
      INTERVAL_MINUTES="$1"
      ;;
    --remove)
      REMOVE="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

[[ "${EUID}" -eq 0 ]] || { echo "Run as root or with sudo." >&2; exit 1; }

if ! command -v crontab >/dev/null 2>&1; then
  if [[ "${REMOVE}" == "true" ]]; then
    rm -f "${LOGROTATE_FILE}"
    echo "crontab is not installed; removed the managed logrotate policy if present."
    exit 0
  fi
  echo "crontab is required." >&2
  exit 1
fi

existing="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "${existing}" | awk -v begin="${BEGIN_MARKER}" -v end="${END_MARKER}" '
  $0 == begin { skipping=1; next }
  $0 == end { skipping=0; next }
  !skipping { print }
')"

if [[ "${REMOVE}" == "true" ]]; then
  printf '%s\n' "${cleaned}" | crontab -
  rm -f "${LOGROTATE_FILE}"
  echo "Removed the managed DC SaaS auto-update cron and logrotate policy."
  exit 0
fi

[[ -r "${ENV_FILE}" ]] || { echo "Missing environment file: ${ENV_FILE}" >&2; exit 1; }
[[ -x "${UPDATE_SCRIPT}" ]] || { echo "Missing executable updater: ${UPDATE_SCRIPT}" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"

INTERVAL_MINUTES="${INTERVAL_MINUTES:-${SAAS_AUTO_UPDATE_INTERVAL_MINUTES:-5}}"
[[ "${INTERVAL_MINUTES}" =~ ^[0-9]+$ ]] && (( INTERVAL_MINUTES >= 1 && INTERVAL_MINUTES <= 60 )) || {
  echo "Interval must be an integer from 1 through 60 minutes." >&2
  exit 1
}

if (( INTERVAL_MINUTES == 60 )); then
  schedule="0 * * * *"
else
  schedule="*/${INTERVAL_MINUTES} * * * *"
fi

install -d -m 0750 "${DEPLOY_ROOT}/log"
log_file="${DEPLOY_ROOT}/log/auto-update-saas.log"
touch "${log_file}"
chmod 0640 "${log_file}"

{
  printf '%s\n' "${cleaned}"
  printf '%s\n' "${BEGIN_MARKER}"
  printf '%s PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin %q >> %q 2>&1\n' \
    "${schedule}" "${UPDATE_SCRIPT}" "${log_file}"
  printf '%s\n' "${END_MARKER}"
} | awk 'NF || previous { print } { previous=NF }' | crontab -

cat > "${LOGROTATE_FILE}" <<EOF
${log_file} {
    size 10M
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
EOF
chmod 0644 "${LOGROTATE_FILE}"

echo "Installed DC SaaS auto-update every ${INTERVAL_MINUTES} minute(s)."
crontab -l | sed -n "/${BEGIN_MARKER}/,/${END_MARKER}/p"
