#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${MANIFEST_DIR:-${SCRIPT_DIR}/.cluster-dev}"
ORDER_MANIFEST="${ORDER_MANIFEST:-${MANIFEST_DIR}/ordersvr-build-manifest.env}"
GW_MANIFEST="${GW_MANIFEST:-${MANIFEST_DIR}/gw-build-manifest.env}"

log() {
  printf '[cluster-dev-verify] %s\n' "$*"
}

die() {
  printf '[cluster-dev-verify] ERROR: %s\n' "$*" >&2
  exit 1
}

label() {
  docker image inspect "$1" --format "{{ index .Config.Labels \"$2\" }}"
}

common_hash_in_image() {
  local image="$1"
  local service="$2"
  docker run --rm --entrypoint sh "${image}" -c "
    set -eu
    set -- /srv/dc/dc/${service}/lib/com.app.common-*.jar
    [ -e \"\$1\" ]
    [ \"\$#\" -eq 1 ]
    sha256sum \"\$1\" | awk '{print \$1}'
  "
}

command -v docker >/dev/null 2>&1 || die "Missing required command: docker"
[[ -r "${ORDER_MANIFEST}" ]] || die "Cannot read ${ORDER_MANIFEST}"
[[ -r "${GW_MANIFEST}" ]] || die "Cannot read ${GW_MANIFEST}"

set -a
# shellcheck disable=SC1090
. "${ORDER_MANIFEST}"
order_image="${ORDERSVR_IMAGE:?ORDERSVR_IMAGE is missing}"
order_common_revision="${COMMON_REVISION:?COMMON_REVISION is missing}"
order_common_hash="${COMMON_JAR_SHA256:?COMMON_JAR_SHA256 is missing}"
# shellcheck disable=SC1090
. "${GW_MANIFEST}"
gw_image="${GW_IMAGE:?GW_IMAGE is missing}"
gw_common_revision="${COMMON_REVISION:?COMMON_REVISION is missing}"
gw_common_hash="${COMMON_JAR_SHA256:?COMMON_JAR_SHA256 is missing}"
set +a

docker image inspect "${order_image}" >/dev/null 2>&1 || die "Missing image ${order_image}"
docker image inspect "${gw_image}" >/dev/null 2>&1 || die "Missing image ${gw_image}"

[[ "$(label "${order_image}" dc.common.revision)" == "${order_common_revision}" ]] ||
  die "OrderSvr common revision label mismatch"
[[ "$(label "${order_image}" dc.common.jar.sha256)" == "${order_common_hash}" ]] ||
  die "OrderSvr common SHA-256 label mismatch"
[[ "$(label "${gw_image}" dc.common.revision)" == "${gw_common_revision}" ]] ||
  die "GW common revision label mismatch"
[[ "$(label "${gw_image}" dc.common.jar.sha256)" == "${gw_common_hash}" ]] ||
  die "GW common SHA-256 label mismatch"

order_image_hash="$(common_hash_in_image "${order_image}" OrderSvr)"
gw_image_hash="$(common_hash_in_image "${gw_image}" GW)"
[[ "${order_image_hash}" == "${order_common_hash}" ]] || die "OrderSvr embedded Common JAR hash mismatch"
[[ "${gw_image_hash}" == "${gw_common_hash}" ]] || die "GW embedded Common JAR hash mismatch"
[[ "${order_image_hash}" == "${gw_image_hash}" ]] || die "OrderSvr and GW embed different Common JARs"

log "OrderSvr image: ${order_image}"
log "GW image: ${gw_image}"
log "Common revision: ${order_common_revision}"
log "Common JAR SHA-256: ${order_image_hash}"
log "Image provenance and embedded dependency checks passed"
