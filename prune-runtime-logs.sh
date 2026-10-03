#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"

[[ -f "${ENV_FILE}" ]] || {
  echo "Missing environment file: ${ENV_FILE}" >&2
  exit 1
}

# shellcheck disable=SC1090
set -a && . "${ENV_FILE}" && set +a
: "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"

LOG_DIR="${DEPLOY_ROOT}/log"
RETENTION_DAYS="${APPLICATION_LOG_RETENTION_DAYS:-14}"
COMPRESS_AFTER_DAYS="${APPLICATION_LOG_COMPRESS_AFTER_DAYS:-1}"

[[ "${DEPLOY_ROOT}" == /* ]] || {
  echo "DEPLOY_ROOT must be an absolute path." >&2
  exit 1
}
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || {
  echo "APPLICATION_LOG_RETENTION_DAYS must be a non-negative integer." >&2
  exit 1
}
[[ "${COMPRESS_AFTER_DAYS}" =~ ^[0-9]+$ ]] || {
  echo "APPLICATION_LOG_COMPRESS_AFTER_DAYS must be a non-negative integer." >&2
  exit 1
}
[[ -d "${LOG_DIR}" ]] || exit 0

find "${LOG_DIR}" -maxdepth 1 -type f \
  \( -name '*.log.????-??-??' -o -name '*.log.????-??-??.gz' \) \
  -mtime "+${RETENTION_DAYS}" -delete

while IFS= read -r -d '' archived_log; do
  if command -v ionice >/dev/null 2>&1; then
    nice -n 19 ionice -c 3 gzip -1 -- "${archived_log}"
  else
    nice -n 19 gzip -1 -- "${archived_log}"
  fi
done < <(
  find "${LOG_DIR}" -maxdepth 1 -type f -name '*.log.????-??-??' \
    -mtime "+${COMPRESS_AFTER_DAYS}" -print0
)
