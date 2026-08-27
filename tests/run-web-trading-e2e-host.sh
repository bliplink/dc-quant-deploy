#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
E2E_BASE_URL="${E2E_BASE_URL:-}"
E2E_LOCATION="${E2E_LOCATION:-WEB_E2E}"
E2E_BUYER="${E2E_BUYER:-webbuyer}"
E2E_SELLER="${E2E_SELLER:-webseller}"
E2E_RUNNER_NAME="${E2E_RUNNER_NAME:-dc-saas-web-e2e-runner}"
E2E_RUNNER_IMAGE="${E2E_RUNNER_IMAGE:-mcr.microsoft.com/playwright:v1.55.0-noble}"

log() {
  printf '[web-e2e-host] %s\n' "$*"
}

die() {
  printf '[web-e2e-host] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
[[ -n "${E2E_PASSWORD:-}" ]] || die "E2E_PASSWORD is required"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:${WEB_LISTEN_PORT}}"
artifact_dir="${E2E_ARTIFACT_DIR:-${DEPLOY_ROOT}/e2e-artifacts}"
install -d -m 0750 "${artifact_dir}"

ENV_FILE="${ENV_FILE}" \
E2E_LOCATION="${E2E_LOCATION}" \
E2E_BUYER="${E2E_BUYER}" \
E2E_SELLER="${E2E_SELLER}" \
E2E_PASSWORD="${E2E_PASSWORD}" \
  "${SCRIPT_DIR}/prepare-web-trading-e2e.sh"

login_api_check() {
  local user="$1"
  local request_file response
  request_file="$(mktemp)"
  chmod 0600 "${request_file}"
  cat >"${request_file}" <<JSON
{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"${user}","user_name":"${user}","password":"${E2E_PASSWORD}","method":"login","client_type":"WEB","cid":"E2E_PRECHECK_${user}","Location":"${E2E_LOCATION}"}}
JSON
  response="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' --data-binary "@${request_file}" "${E2E_BASE_URL}/httpapi/")" || {
    rm -f "${request_file}"
    die "Login API request failed for ${user}"
  }
  rm -f "${request_file}"
  grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${response}" || die "Login API rejected ${user}"
  grep -Fq "\"user_id\":\"${user}\"" <<<"${response}" || die "Login API returned another user for ${user}"
}

login_api_check "${E2E_BUYER}"
login_api_check "${E2E_SELLER}"

wrong_location_request="$(mktemp)"
chmod 0600 "${wrong_location_request}"
cat >"${wrong_location_request}" <<JSON
{"serverName":"LoginSvr","method":"SYS.ATS.LOGIN","content":{"user_id":"${E2E_BUYER}","user_name":"${E2E_BUYER}","password":"${E2E_PASSWORD}","method":"login","client_type":"WEB","cid":"E2E_WRONG_LOCATION","Location":"${E2E_LOCATION}_WRONG"}}
JSON
wrong_location_response="$(curl -fsS --max-time 20 -H 'Content-Type: application/json' --data-binary "@${wrong_location_request}" "${E2E_BASE_URL}/httpapi/")" || {
  rm -f "${wrong_location_request}"
  die "Wrong-location login precheck could not reach LoginSvr"
}
rm -f "${wrong_location_request}"
if grep -Eq '"code"[[:space:]]*:[[:space:]]*0' <<<"${wrong_location_response}"; then
  die "LoginSvr accepted valid credentials under the wrong location"
fi
log "Login API precheck passed and wrong-location authentication was rejected."

runner_state="$(docker inspect --format '{{.State.Status}}' "${E2E_RUNNER_NAME}" 2>/dev/null || true)"
if [[ -z "${runner_state}" ]]; then
  log "Creating reusable Playwright runner ${E2E_RUNNER_NAME}."
  docker run -d \
    --name "${E2E_RUNNER_NAME}" \
    --network host \
    --label dc.saas.role=web-e2e-runner \
    -v "${SCRIPT_DIR}:/work:ro" \
    -v "${artifact_dir}:/artifacts" \
    -v dc-saas-web-e2e-npm-cache:/root/.npm \
    -v dc-saas-web-e2e-runner:/runner \
    "${E2E_RUNNER_IMAGE}" sleep infinity >/dev/null
else
  runner_role="$(docker inspect --format '{{index .Config.Labels "dc.saas.role"}}' "${E2E_RUNNER_NAME}")"
  [[ "${runner_role}" == "web-e2e-runner" ]] ||
    die "Container ${E2E_RUNNER_NAME} exists but is not a SaaS web E2E runner"
  if [[ "${runner_state}" != "running" ]]; then
    docker start "${E2E_RUNNER_NAME}" >/dev/null
  fi
fi

docker exec \
  -e E2E_BASE_URL="${E2E_BASE_URL}" \
  -e E2E_LOCATION="${E2E_LOCATION}" \
  -e E2E_BUYER="${E2E_BUYER}" \
  -e E2E_SELLER="${E2E_SELLER}" \
  -e E2E_PASSWORD="${E2E_PASSWORD}" \
  -e E2E_ARTIFACT_DIR=/artifacts \
  "${E2E_RUNNER_NAME}" bash /work/run-web-trading-e2e.sh

log "Browser trading acceptance passed; artifacts: ${artifact_dir}."
