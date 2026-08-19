#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATE_SCRIPT="${ROOT_DIR}/auto-update-service.sh"
SERVICES=(gateway loginsvr mdsvr apssvr quantsvr indsvr customindsvr simsvr batchsvr web zookeeper clickhouse)

[[ -x "${UPDATE_SCRIPT}" ]] || {
  echo "Missing executable updater: ${UPDATE_SCRIPT}" >&2
  exit 1
}

failed=()
for service in "${SERVICES[@]}"; do
  container="dc-${service}"
  if [[ "${service}" == "gateway" ]]; then
    container="dc-gateway"
  fi
  if ! docker container inspect "${container}" >/dev/null 2>&1; then
    echo "Skip ${service}: container ${container} is not deployed."
    continue
  fi
  echo "===== Checking ${service} ====="
  if ! "${UPDATE_SCRIPT}" "${service}"; then
    failed+=("${service}")
  fi
done

if [[ "${#failed[@]}" -gt 0 ]]; then
  echo "Auto update failed for: ${failed[*]}" >&2
  exit 1
fi

echo "All deployed application services are up to date."
