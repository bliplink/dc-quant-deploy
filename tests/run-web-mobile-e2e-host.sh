#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_LOCATION="${E2E_LOCATION:-WEB_E2E}"
E2E_USER="${E2E_USER:-webbuyer}"
E2E_RUNNER_NAME="${E2E_RUNNER_NAME:-dc-saas-web-e2e-runner}"
E2E_RUNNER_IMAGE="${E2E_RUNNER_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"

[[ -r "${ENV_FILE}" ]] || { echo "Cannot read ${ENV_FILE}" >&2; exit 1; }
[[ -n "${E2E_PASSWORD:-}" ]] || { echo 'E2E_PASSWORD is required' >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}}"
artifact_dir="${E2E_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts}"
install -d -m 0750 "${artifact_dir}"

runner_state="$(docker inspect --format '{{.State.Status}}' "${E2E_RUNNER_NAME}" 2>/dev/null || true)"
if [[ -z "${runner_state}" ]]; then
  docker run -d --name "${E2E_RUNNER_NAME}" --network host \
    --label dc.saas.role=web-e2e-runner \
    -v "${SCRIPT_DIR}:/work:ro" -v "${artifact_dir}:/artifacts" \
    -v dc-saas-web-e2e-npm-cache:/root/.npm -v dc-saas-web-e2e-runner:/runner \
    "${E2E_RUNNER_IMAGE}" sleep infinity >/dev/null
elif [[ "${runner_state}" != "running" ]]; then
  docker start "${E2E_RUNNER_NAME}" >/dev/null
fi

docker exec \
  -e E2E_BASE_URL="${E2E_BASE_URL}" \
  -e E2E_LOCATION="${E2E_LOCATION}" \
  -e E2E_USER="${E2E_USER}" \
  -e E2E_PASSWORD="${E2E_PASSWORD}" \
  -e E2E_ARTIFACT_DIR=/artifacts \
  "${E2E_RUNNER_NAME}" bash -lc \
  'cd /runner && [[ -f package.json ]] || npm init -y >/dev/null 2>&1; [[ -d node_modules/playwright ]] || npm install --no-fund --no-audit playwright@1.55.0 >/dev/null; NODE_PATH=/runner/node_modules node /work/web-mobile-e2e.js'

printf '[web-mobile-e2e] PASS; artifacts: %s\n' "${artifact_dir}"
