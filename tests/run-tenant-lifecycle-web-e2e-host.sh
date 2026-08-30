#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_SUFFIX="${E2E_SUFFIX:-$(date +%m%d%H%M%S)}"
E2E_LOCATION_A="${E2E_LOCATION_A:-SAASA_E2E_${E2E_SUFFIX}}"
E2E_LOCATION_B="${E2E_LOCATION_B:-SAASB_E2E_${E2E_SUFFIX}}"
E2E_ADMIN_USER="${E2E_ADMIN_USER:-tenantadmin}"
E2E_RUNNER_NAME="${E2E_RUNNER_NAME:-dc-saas-web-e2e-runner}"
E2E_RUNNER_IMAGE="${E2E_RUNNER_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"

[[ "$(id -u)" -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
[[ -r "${ENV_FILE}" ]] || { echo "Cannot read ${ENV_FILE}" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}}"
artifact_dir="${E2E_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts/tenant-${E2E_SUFFIX}}"
admin_password_a="$(openssl rand -hex 16)"
admin_password_b="$(openssl rand -hex 16)"
trader_password_a="$(openssl rand -hex 16)"
trader_password_b="$(openssl rand -hex 16)"
install -d -m 0750 "${artifact_dir}"

E2E_SUFFIX="${E2E_SUFFIX}" \
E2E_LOCATION_A="${E2E_LOCATION_A}" E2E_LOCATION_B="${E2E_LOCATION_B}" \
E2E_ADMIN_USER="${E2E_ADMIN_USER}" \
E2E_ADMIN_PASSWORD_A="${admin_password_a}" E2E_ADMIN_PASSWORD_B="${admin_password_b}" \
E2E_TRADER_PASSWORD_A="${trader_password_a}" E2E_TRADER_PASSWORD_B="${trader_password_b}" \
  "${SCRIPT_DIR}/run-tenant-lifecycle-e2e-host.sh"

runner_state="$(docker inspect --format '{{.State.Status}}' "${E2E_RUNNER_NAME}" 2>/dev/null || true)"
if [[ -n "${runner_state}" ]]; then
  runner_work_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/work"}}{{.Source}}{{end}}{{end}}' "${E2E_RUNNER_NAME}")"
  if [[ "${runner_work_source}" != "${SCRIPT_DIR}" ]]; then
    docker rm -f "${E2E_RUNNER_NAME}" >/dev/null
    runner_state=""
  fi
fi
if [[ -z "${runner_state}" ]]; then
  docker run -d --name "${E2E_RUNNER_NAME}" --network host \
    --label dc.saas.role=web-e2e-runner \
    -v "${SCRIPT_DIR}:/work:ro" -v "${DEPLOY_ROOT}/e2e-artifacts:/artifacts" \
    -v dc-saas-web-e2e-npm-cache:/root/.npm -v dc-saas-web-e2e-runner:/runner \
    "${E2E_RUNNER_IMAGE}" sleep infinity >/dev/null
elif [[ "${runner_state}" != "running" ]]; then
  docker start "${E2E_RUNNER_NAME}" >/dev/null
fi

container_artifact_dir="/artifacts/tenant-${E2E_SUFFIX}"
docker exec \
  -e E2E_BASE_URL="${E2E_BASE_URL}" \
  -e E2E_LOCATION_A="${E2E_LOCATION_A}" -e E2E_LOCATION_B="${E2E_LOCATION_B}" \
  -e E2E_ADMIN_USER="${E2E_ADMIN_USER}" -e E2E_ADMIN_PASSWORD_A="${admin_password_a}" \
  -e PLATFORM_ADMIN_USERNAME="${PLATFORM_ADMIN_USERNAME}" -e PLATFORM_ADMIN_PASSWORD="${PLATFORM_ADMIN_PASSWORD}" \
  -e E2E_ARTIFACT_DIR="${container_artifact_dir}" \
  "${E2E_RUNNER_NAME}" bash -lc \
  'cd /runner && [[ -f package.json ]] || npm init -y >/dev/null 2>&1; [[ -d node_modules/playwright ]] || npm install --no-fund --no-audit playwright@1.55.0 >/dev/null; NODE_PATH=/runner/node_modules node /work/tenant-lifecycle-web-e2e.js'

printf '[tenant-web-e2e] PASS; locations: %s, %s; artifacts: %s\n' \
  "${E2E_LOCATION_A}" "${E2E_LOCATION_B}" "${artifact_dir}"
