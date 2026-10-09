#!/usr/bin/env bash
# No-credentials preflight for the isolated Broker E2E Java entrypoint.
# No tenant registration, authentication, Docker restart or broker trades.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${BROKER_E2E_RUNNER_IMAGE_REF:-ghcr.io/bliplink/robotsvr:sha-36b80cfca6c70e9c13e1b5f0114b4eb87d0d9872}"

[[ "${IMAGE}" =~ ^ghcr[.]io/bliplink/robotsvr:sha-[a-f0-9]{40}$ ]] || {
  printf '%s\n' 'FAIL: only an exact RobotSvr GHCR commit-SHA image is supported' >&2
  exit 2
}
command -v docker >/dev/null || { echo 'FAIL: docker not found' >&2; exit 2; }
command -v python3 >/dev/null || { echo 'FAIL: python3 not found' >&2; exit 2; }
image_id="$(docker image inspect --format '{{.Id}}' "${IMAGE}" 2>/dev/null || true)"
[[ -n "${image_id}" ]] || {
  echo 'FAIL: pinned candidate image not available locally' >&2
  exit 2
}
python3 "${SCRIPT_DIR}/broker-runner-image-review.py" "${image_id}" >/dev/null
arch="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${IMAGE}")"
[[ "${arch}" == linux/arm64 || "${arch}" == linux/amd64 ]] || {
  echo 'FAIL: unexpected image platform' >&2
  exit 2
}

# Forcefully isolate networking. Without even a tenant location, the runner
# must reject its input before attempting key signing or customer operations.
set +e
run_output="$(docker run --rm --network none --memory=256m --cpus=1 \
  -e MAIN_CLASS=com.app.dc.robot.BrokerApiE2ERunner \
  -e JAVA_OPTS='-Xms32m -Xmx96m' "${image_id}" 2>&1)"
runner_rc=$?
set -e
if [[ "${runner_rc}" == 0 ]] || ! grep -Fq 'BROKER_E2E_LOCATION is required' <<< "${run_output}"; then
  # Never print any raw container output, even on preflight failures.
  echo 'FAIL: expected safe missing-tenant rejection not observed' >&2
  exit 1
fi
echo "BROKER_RUNNER_OFFLINE_PREFLIGHT_PASS image_id=${image_id} platform=${arch}"
