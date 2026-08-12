#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
UPDATE_SCRIPT="${ROOT_DIR}/auto-update-all-services.sh"
BEGIN_MARKER="# BEGIN DC AUTO UPDATE"
END_MARKER="# END DC AUTO UPDATE"

[[ "${EUID}" -eq 0 ]] || {
  echo "Run this installer with sudo." >&2
  exit 1
}
[[ -f "${ENV_FILE}" ]] || {
  echo "Missing environment file: ${ENV_FILE}" >&2
  exit 1
}
[[ -x "${UPDATE_SCRIPT}" ]] || {
  echo "Missing executable updater: ${UPDATE_SCRIPT}" >&2
  exit 1
}

# shellcheck disable=SC1090
set -a && . "${ENV_FILE}" && set +a
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"
mkdir -p "${DEPLOY_ROOT}/log"

existing="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "${existing}" | awk -v begin="${BEGIN_MARKER}" -v end="${END_MARKER}" '
  $0 == begin { skipping=1; next }
  $0 == end { skipping=0; next }
  !skipping { print }
')"

{
  printf '%s\n' "${cleaned}"
  printf '%s\n' "${BEGIN_MARKER}"
  printf '* * * * * /usr/bin/flock -n /tmp/dc-auto-update-all-cron.lock %q >> %q 2>&1\n' \
    "${UPDATE_SCRIPT}" "${DEPLOY_ROOT}/log/auto-update-all-services.log"
  printf '%s\n' "${END_MARKER}"
} | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -

echo "Installed one-minute auto-update cron for all deployed application services."
crontab -l | sed -n "/${BEGIN_MARKER}/,/${END_MARKER}/p"
