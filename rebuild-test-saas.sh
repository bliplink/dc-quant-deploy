#!/usr/bin/env bash
set -euo pipefail

# Disposable dc-saas test environment only. No business-data backups are taken.
# Run on the Linux Docker host; the normal uninstall preserves code/build cache.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK=""; BUILD_DIR=""; M2_DIR=""; SETTINGS=""; RESET_ID=""; CONFIRM=""; SKIP_BUILD=false
INPUT_ENV="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock) LOCK="$2"; shift 2 ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --m2) M2_DIR="$2"; shift 2 ;;
    --settings) SETTINGS="$2"; shift 2 ;;
    --reset-id) RESET_ID="$2"; shift 2 ;;
    --confirm-root) CONFIRM="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ ${EUID} == 0 && -n "${LOCK}" && -n "${BUILD_DIR}" && -n "${RESET_ID}" ]] || {
  printf 'Require root, --lock, --build-dir, --reset-id, --confirm-root (and --m2/--settings unless --skip-build).\n' >&2; exit 2;
}
[[ "${CONFIRM}" == /data/dc-saas-runtime || "${CONFIRM}" == /opt/dc-saas-runtime ]] || exit 2
[[ -r "${INPUT_ENV}" && "${RESET_ID}" =~ ^reset-[A-Za-z0-9-]{8,80}$ ]] || exit 2

if [[ "${SKIP_BUILD}" != true ]]; then
  python3 "${SCRIPT_DIR}/tests/build-locked-release.py" --lock "${LOCK}" --build-root "${BUILD_DIR}" \
    --m2 "${M2_DIR}" --settings "${SETTINGS}" --cached-web-bases \
    --prerequisite-lock "${SCRIPT_DIR}/docs/evidence/full-release-connector-lock-20260929.json" \
    --prerequisite-root "${BUILD_DIR}/connector-prerequisite"
fi

RELEASE_ENV="${SCRIPT_DIR}/.env.${RESET_ID}"
python3 "${SCRIPT_DIR}/tests/prepare-locked-release-env.py" --lock "${LOCK}" \
  --build-evidence "${BUILD_DIR}/build-evidence.json" --input-env "${INPUT_ENV}" --output-env "${RELEASE_ENV}"
set -a; . "${RELEASE_ENV}"; set +a
[[ "${DEPLOY_ROOT}" == "${CONFIRM}" ]] || { printf 'Input runtime root differs from confirmation.\n' >&2; exit 2; }
python3 "${SCRIPT_DIR}/tests/reset-saas-test-data.py" --runtime-root "${DEPLOY_ROOT}" --reset-id "${RESET_ID}"

printf '[test-rebuild] Uninstalling only dc-saas; preserving code, config and build cache.\n'
ENV_FILE="${RELEASE_ENV}" "${SCRIPT_DIR}/uninstall-saas.sh"
python3 "${SCRIPT_DIR}/tests/reset-saas-test-data.py" --runtime-root "${DEPLOY_ROOT}" --reset-id "${RESET_ID}" \
  --apply --confirm-root "${CONFIRM}"
printf '[test-rebuild] Deleted old test data without backups; beginning fresh install.\n'
# A bounded 300-order disposable test profile needs 40 GiB headroom, not the
# default production 100 GiB reserve. All memory/Docker-space checks remain on.
SAAS_MIN_RUNTIME_DISK_GB=40 \
SAAS_FRESH_TEST_RESET_PROOF="${DEPLOY_ROOT}/evidence/${RESET_ID}.json" \
  ENV_FILE="${RELEASE_ENV}" "${SCRIPT_DIR}/install-saas.sh" --full-cluster --skip-host-prepare --skip-pull
ENV_FILE="${RELEASE_ENV}" ACCEPTANCE_RUN_ID="${RESET_ID}" ACCEPTANCE_STRESS_ORDERS=300 \
  ACCEPTANCE_STRESS_CONCURRENCY=16 "${SCRIPT_DIR}/acceptance-saas.sh"
printf '[test-rebuild] PASS: fresh install, API initialization, 300/16 business acceptance.\n'
