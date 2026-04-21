#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.prod"
CONTROL_DIR="${SCRIPT_DIR}/control.prod"
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
OVERRIDE_FILE="${SCRIPT_DIR}/compose.override.generated.yaml"
GENERATE_OVERRIDES_SCRIPT="${SCRIPT_DIR}/generate-compose-overrides.sh"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_file() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    echo "missing required file: ${file}" >&2
    exit 1
  fi
}

require_dir() {
  local dir="$1"
  if [[ ! -d "${dir}" ]]; then
    echo "missing required directory: ${dir}" >&2
    exit 1
  fi
}

check_no_placeholders() {
  local file="$1"
  if grep -q '{{' "${file}"; then
    echo "placeholder still present in ${file}" >&2
    exit 1
  fi
}

require_command docker
require_file "${ENV_FILE}"
require_dir "${CONTROL_DIR}"

# shellcheck disable=SC1090
source "${ENV_FILE}"

require_file "${CONTROL_DIR}/ATSConfig.ini"
require_file "${CONTROL_DIR}/DBPoolConfig.ini"
require_file "${CONTROL_DIR}/jaas.ini"
require_file "${CONTROL_DIR}/dc.dat"

check_no_placeholders "${CONTROL_DIR}/ATSConfig.ini"
check_no_placeholders "${CONTROL_DIR}/DBPoolConfig.ini"
check_no_placeholders "${CONTROL_DIR}/jaas.ini"

if [[ -z "${DEPLOY_ROOT:-}" ]]; then
  echo "DEPLOY_ROOT is required in .env.prod" >&2
  exit 1
fi

if [[ -z "${CLICKHOUSE_MODE:-}" ]]; then
  echo "CLICKHOUSE_MODE is required in .env.prod" >&2
  exit 1
fi

if [[ "${CLICKHOUSE_MODE}" != "embedded" && "${CLICKHOUSE_MODE}" != "external" ]]; then
  echo "CLICKHOUSE_MODE must be embedded or external" >&2
  exit 1
fi

for tag_var in CLICKHOUSE_IMAGE_TAG CLICKHOUSE_DB_NAME CLICKHOUSE_HOST CLICKHOUSE_HTTP_PORT CLICKHOUSE_NATIVE_PORT CLICKHOUSE_USERNAME ZOOKEEPER_TAG GW_TAG MDSVR_TAG APSSVR_TAG QUANTSVR_TAG INDSVR_TAG SIMSVR_TAG BATCHSVR_TAG WEB_TAG; do
  if [[ -z "${!tag_var:-}" ]]; then
    echo "${tag_var} is required in .env.prod" >&2
    exit 1
  fi
done

if [[ ! -d "${DEPLOY_ROOT}" ]]; then
  mkdir -p "${DEPLOY_ROOT}" || {
    echo "DEPLOY_ROOT cannot be created: ${DEPLOY_ROOT}" >&2
    exit 1
  }
fi

if cmp -s "${CONTROL_DIR}/dc.dat" "${SCRIPT_DIR}/control.prod.example/dc.dat"; then
  echo "control.prod/dc.dat is still the example placeholder. Replace it with the real runtime content." >&2
  exit 1
fi

require_file "${SCRIPT_DIR}/clickhouse/init/00-create-db.sql"
require_file "${SCRIPT_DIR}/clickhouse/init/01-run-all.sh"
require_file "${SCRIPT_DIR}/clickhouse/apply-init.sh"
require_dir "${SCRIPT_DIR}/clickhouse/init/10-schema"
require_dir "${SCRIPT_DIR}/clickhouse/init/20-view"
require_dir "${SCRIPT_DIR}/clickhouse/init/90-optional-seed"
require_file "${GENERATE_OVERRIDES_SCRIPT}"

if [[ ! -f "${HOME}/.docker/config.json" ]]; then
  if [[ "${REQUIRE_GHCR_LOGIN:-false}" == "true" ]]; then
    echo "docker login not found: ${HOME}/.docker/config.json missing" >&2
    exit 1
  fi
  echo "Warning: docker login not found: ${HOME}/.docker/config.json missing; continuing because REQUIRE_GHCR_LOGIN is not true." >&2
elif ! grep -q "ghcr.io" "${HOME}/.docker/config.json"; then
  if [[ "${REQUIRE_GHCR_LOGIN:-false}" == "true" ]]; then
    echo "GHCR login not found in ${HOME}/.docker/config.json" >&2
    exit 1
  fi
  echo "Warning: GHCR login not found in ${HOME}/.docker/config.json; continuing because REQUIRE_GHCR_LOGIN is not true." >&2
fi

bash "${GENERATE_OVERRIDES_SCRIPT}" "${ENV_FILE}" "${OVERRIDE_FILE}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" -f "${OVERRIDE_FILE}" config > "${SCRIPT_DIR}/.compose.config.check.yaml"

if grep -Eq 'source: .*/tpc/zookeeper|source: .*/dc/GW/config' "${SCRIPT_DIR}/.compose.config.check.yaml"; then
  echo "compose config still contains a deprecated tpc/zookeeper or dc/GW/config mount" >&2
  rm -f "${SCRIPT_DIR}/.compose.config.check.yaml"
  exit 1
fi

rm -f "${SCRIPT_DIR}/.compose.config.check.yaml"

echo "Validation passed."
