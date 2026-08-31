#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_LOCATION="${E2E_LOCATION:-WEB_E2E}"
E2E_USER="${E2E_USER:-webbuyer}"
E2E_RUNNER_NAME="${E2E_RUNNER_NAME:-dc-saas-web-e2e-runner}"
E2E_RUNNER_IMAGE="${E2E_RUNNER_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"

log() { printf '[web-session-e2e] %s\n' "$*"; }
die() { printf '[web-session-e2e] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}}"
artifact_dir="${E2E_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts}"
install -d -m 0750 "${artifact_dir}"

for service in dc-saas-gateway dc-saas-loginsvr dc-saas-trade-web; do
  [[ "$(docker inspect --format '{{.State.Status}}' "${service}" 2>/dev/null || true)" == running ]] ||
    die "${service} is not running"
done

runner_state="$(docker inspect --format '{{.State.Status}}' "${E2E_RUNNER_NAME}" 2>/dev/null || true)"
if [[ -z "${runner_state}" ]]; then
  docker run -d --name "${E2E_RUNNER_NAME}" --network host \
    --label dc.saas.role=web-e2e-runner \
    -v "${SCRIPT_DIR}:/work:ro" -v "${artifact_dir}:/artifacts" \
    -v dc-saas-web-e2e-npm-cache:/root/.npm -v dc-saas-web-e2e-runner:/runner \
    "${E2E_RUNNER_IMAGE}" sleep infinity >/dev/null
elif [[ "${runner_state}" != running ]]; then
  docker start "${E2E_RUNNER_NAME}" >/dev/null
fi

log "Testing refresh, network reconnect, token replay, tenant mismatch and logout."
disconnect_marker="${artifact_dir}/websocket-session-disconnect.ready"
rm -f "${disconnect_marker}"
trap 'rm -f "${disconnect_marker}"' EXIT
docker exec \
  -e E2E_BASE_URL="${E2E_BASE_URL}" -e E2E_LOCATION="${E2E_LOCATION}" \
  -e E2E_USER="${E2E_USER}" -e E2E_PASSWORD="${E2E_PASSWORD}" \
  -e E2E_ARTIFACT_DIR=/artifacts \
  "${E2E_RUNNER_NAME}" bash -lc '
    cd /runner
    [[ -f package.json ]] || npm init -y >/dev/null 2>&1
    [[ -d node_modules/playwright ]] || npm install --no-audit --no-fund playwright@1.55.0 >/dev/null
    NODE_PATH=/runner/node_modules node /work/web-session-resume-e2e.js
  ' &
test_pid="$!"

for attempt in $(seq 1 120); do
  if [[ -f "${disconnect_marker}" ]]; then break; fi
  if ! kill -0 "${test_pid}" 2>/dev/null; then
    wait "${test_pid}"
    die "Browser test exited before the disconnect checkpoint"
  fi
  sleep 0.5
done
[[ -f "${disconnect_marker}" ]] || {
  kill "${test_pid}" 2>/dev/null || true
  wait "${test_pid}" 2>/dev/null || true
  die "Browser test did not reach the disconnect checkpoint"
}

log "Restarting only dc-saas-trade-web to drop the active WebSocket without reloading the page."
docker restart dc-saas-trade-web >/dev/null
for attempt in $(seq 1 60); do
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' dc-saas-trade-web 2>/dev/null || true)" == healthy ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.Health.Status}}' dc-saas-trade-web 2>/dev/null || true)" == healthy ]] ||
  die "dc-saas-trade-web did not become healthy after disconnect simulation"
rm -f "${disconnect_marker}"
wait "${test_pid}"
