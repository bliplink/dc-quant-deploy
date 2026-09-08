#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
COMMON_LIBRARY_SOURCE="${COMMON_LIBRARY_SOURCE:-${WORKSPACE_ROOT}/com.app.common}"
DC_COMMON_SOURCE="${DC_COMMON_SOURCE:-${WORKSPACE_ROOT}/com.app.dc}"
ORDERSVR_SOURCE="${ORDERSVR_SOURCE:-${WORKSPACE_ROOT}/ordersvr}"
PROJECTIONSVR_SOURCE="${PROJECTIONSVR_SOURCE:-${WORKSPACE_ROOT}/projectionsvr}"
GATEWAY_LIBRARY_SOURCE="${GATEWAY_LIBRARY_SOURCE:-${WORKSPACE_ROOT}/gateway/gateway}"
GATEWAY_IMAGE_SOURCE="${GATEWAY_IMAGE_SOURCE:-${WORKSPACE_ROOT}/gw-image}"
MDSVR_SOURCE="${MDSVR_SOURCE:-${WORKSPACE_ROOT}/mdsvr}"
TRADESVR_SOURCE="${TRADESVR_SOURCE:-${WORKSPACE_ROOT}/tradesvr}"
LIQSVR_SOURCE="${LIQSVR_SOURCE:-${WORKSPACE_ROOT}/liqsvr}"
M2_ROOT="${M2_ROOT:-${SCRIPT_DIR}/.cluster-dev/m2-linux}"
MAVEN_BUILD_IMAGE="${MAVEN_BUILD_IMAGE:-maven:3.9.11-eclipse-temurin-8}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-dc-saas/ordersvr}"
GATEWAY_IMAGE_REPOSITORY="${GATEWAY_IMAGE_REPOSITORY:-dc-saas/gw}"
MDSVR_IMAGE_REPOSITORY="${MDSVR_IMAGE_REPOSITORY:-dc-saas/mdsvr}"
TRADESVR_IMAGE_REPOSITORY="${TRADESVR_IMAGE_REPOSITORY:-dc-saas/tradesvr}"
LIQSVR_IMAGE_REPOSITORY="${LIQSVR_IMAGE_REPOSITORY:-dc-saas/liqsvr}"
PROJECTIONSVR_IMAGE_REPOSITORY="${PROJECTIONSVR_IMAGE_REPOSITORY:-dc-saas/projectionsvr}"
INCLUDE_GATEWAY="${INCLUDE_GATEWAY:-false}"
INCLUDE_CORE_CONSUMERS="${INCLUDE_CORE_CONSUMERS:-false}"
PUSH_IMAGES="${PUSH_IMAGES:-false}"
SKIP_TESTS="${SKIP_TESTS:-false}"
SKIP_MAVEN_BUILD="${SKIP_MAVEN_BUILD:-false}"
SKIP_DOCKER_BUILD="${SKIP_DOCKER_BUILD:-false}"

log() {
  printf '[cluster-dev] %s\n' "$*"
}

die() {
  printf '[cluster-dev] ERROR: %s\n' "$*" >&2
  exit 1
}

require_directory() {
  [[ -d "$1" ]] || die "$2 does not exist: $1"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

git_revision() {
  git -C "$1" rev-parse --short=12 HEAD
}

maven() {
  local source_dir="$1"
  shift
  docker run --rm \
    --memory="${MAVEN_MEMORY_LIMIT:-3g}" \
    -e MAVEN_OPTS="${MAVEN_OPTS:--Xms64m -Xmx1024m -XX:+UseSerialGC}" \
    -v "${M2_ROOT}:/root/.m2:Z" \
    -v "${source_dir}:/workspace:Z" \
    -w /workspace \
    "${MAVEN_BUILD_IMAGE}" mvn -B "$@"
}

pom_value() {
  local source_dir="$1"
  local expression="$2"
  maven "${source_dir}" help:evaluate -Dexpression="${expression}" -q -DforceStdout |
    tr -d '\r' | tail -n 1
}

require_command docker
require_command git
require_command sha256sum
require_directory "${COMMON_LIBRARY_SOURCE}" "com.app.common source"
require_directory "${DC_COMMON_SOURCE}" "com.app.dc source"
require_directory "${ORDERSVR_SOURCE}" "OrderSvr source"
if [[ "${INCLUDE_GATEWAY}" == "true" ]]; then
  require_directory "${GATEWAY_LIBRARY_SOURCE}" "gateway library source"
  require_directory "${GATEWAY_IMAGE_SOURCE}" "GW image source"
fi
if [[ "${INCLUDE_CORE_CONSUMERS}" == "true" ]]; then
  require_directory "${PROJECTIONSVR_SOURCE}" "ProjectionSvr source"
  require_directory "${MDSVR_SOURCE}" "MDSvr source"
  require_directory "${TRADESVR_SOURCE}" "TradeSvr source"
  require_directory "${LIQSVR_SOURCE}" "LiqSvr source"
fi
install -d -m 0750 "${M2_ROOT}" "${SCRIPT_DIR}/.cluster-dev"

common_group="$(pom_value "${COMMON_LIBRARY_SOURCE}" project.groupId)"
common_artifact="$(pom_value "${COMMON_LIBRARY_SOURCE}" project.artifactId)"
common_version="$(pom_value "${COMMON_LIBRARY_SOURCE}" project.version)"
dc_group="$(pom_value "${DC_COMMON_SOURCE}" project.groupId)"
dc_artifact="$(pom_value "${DC_COMMON_SOURCE}" project.artifactId)"
dc_version="$(pom_value "${DC_COMMON_SOURCE}" project.version)"

common_revision="$(git_revision "${COMMON_LIBRARY_SOURCE}")"
build_output_timestamp="$(git -C "${COMMON_LIBRARY_SOURCE}" show -s --format=%cI HEAD)"
dc_revision="$(git_revision "${DC_COMMON_SOURCE}")"
ordersvr_revision="$(git_revision "${ORDERSVR_SOURCE}")"
common_gav="${common_group}:${common_artifact}:${common_version}"
dc_gav="${dc_group}:${dc_artifact}:${dc_version}"
image_ref="${IMAGE_REPOSITORY}:cluster-dev-${ordersvr_revision}-common-${common_revision}"
build_date="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

log "Isolated Maven repository: ${M2_ROOT}"
log "Common: ${common_gav} @ ${common_revision}"
log "Reproducible build timestamp: ${build_output_timestamp}"
log "DC common: ${dc_gav} @ ${dc_revision}"
log "OrderSvr revision: ${ordersvr_revision}"

if [[ "${SKIP_MAVEN_BUILD}" != "true" ]]; then
  test_arg="-DskipTests=false"
  [[ "${SKIP_TESTS}" != "true" ]] || test_arg="-Dmaven.test.skip=true"
  maven "${COMMON_LIBRARY_SOURCE}" clean install -Dproject.build.outputTimestamp="${build_output_timestamp}" "${test_arg}"
  maven "${DC_COMMON_SOURCE}" clean install -Dproject.build.outputTimestamp="${build_output_timestamp}" "${test_arg}"
  maven "${ORDERSVR_SOURCE}" clean package dependency:copy-dependencies \
    -DoutputDirectory=target/dependency -Dproject.build.outputTimestamp="${build_output_timestamp}" "${test_arg}"
  if [[ "${INCLUDE_GATEWAY}" == "true" ]]; then
    gateway_version="$(pom_value "${GATEWAY_LIBRARY_SOURCE}" project.version)"
    maven "${GATEWAY_LIBRARY_SOURCE}" clean install -Dproject.build.outputTimestamp="${build_output_timestamp}" "${test_arg}"
    maven "${GATEWAY_IMAGE_SOURCE}" clean package dependency:copy-dependencies \
      -DoutputDirectory=target/dependency -Dgateway.version="${gateway_version}" \
      -Dproject.build.outputTimestamp="${build_output_timestamp}" "${test_arg}"
  fi
  if [[ "${INCLUDE_CORE_CONSUMERS}" == "true" ]]; then
    for service_source in "${PROJECTIONSVR_SOURCE}" "${MDSVR_SOURCE}" "${TRADESVR_SOURCE}" "${LIQSVR_SOURCE}"; do
      maven "${service_source}" clean package dependency:copy-dependencies \
        -DoutputDirectory=target/dependency -Dproject.build.outputTimestamp="${build_output_timestamp}" "${test_arg}"
    done
  fi
else
  log "Reusing existing Maven outputs; dependency identity checks remain enabled"
fi

dependency_dir="${ORDERSVR_SOURCE}/target/dependency"
mapfile -t common_jars < <(find "${dependency_dir}" -maxdepth 1 -type f -name "${common_artifact}-*.jar" -print)
mapfile -t dc_jars < <(find "${dependency_dir}" -maxdepth 1 -type f -name "${dc_artifact}-*.jar" -print)
[[ "${#common_jars[@]}" -eq 1 ]] || die "Expected exactly one ${common_artifact} JAR, found ${#common_jars[@]}"
[[ "${#dc_jars[@]}" -eq 1 ]] || die "Expected exactly one ${dc_artifact} JAR, found ${#dc_jars[@]}"

common_jar_hash="$(sha256sum "${common_jars[0]}" | awk '{print $1}')"
dc_jar_hash="$(sha256sum "${dc_jars[0]}" | awk '{print $1}')"

if [[ "${SKIP_DOCKER_BUILD}" != "true" ]]; then
  log "Building immutable development image ${image_ref}"
  docker build \
    --build-arg REPO_URL=https://github.com/bliplink/com.app.dc.ordersvr \
    --build-arg SERVICE_REVISION="${ordersvr_revision}" \
    --build-arg COMMON_REVISION="${common_revision}" \
    --build-arg COMMON_GAV="${common_gav}" \
    --build-arg BUILD_DATE="${build_date}" \
    --label dc.common.jar.sha256="${common_jar_hash}" \
    --label dc.dc-common.revision="${dc_revision}" \
    --label dc.dc-common.jar.sha256="${dc_jar_hash}" \
    --tag "${image_ref}" \
    "${ORDERSVR_SOURCE}"
fi

manifest="${SCRIPT_DIR}/.cluster-dev/ordersvr-build-manifest.env"
{
  printf 'BUILD_DATE=%s\n' "${build_date}"
  printf 'BUILD_OUTPUT_TIMESTAMP=%s\n' "${build_output_timestamp}"
  printf 'ORDERSVR_IMAGE=%s\n' "${image_ref}"
  printf 'ORDERSVR_REVISION=%s\n' "${ordersvr_revision}"
  printf 'DC_COMMON_GAV=%s\n' "${dc_gav}"
  printf 'DC_COMMON_REVISION=%s\n' "${dc_revision}"
  printf 'DC_COMMON_JAR_SHA256=%s\n' "${dc_jar_hash}"
  printf 'COMMON_GAV=%s\n' "${common_gav}"
  printf 'COMMON_REVISION=%s\n' "${common_revision}"
  printf 'COMMON_JAR_SHA256=%s\n' "${common_jar_hash}"
} > "${manifest}"

log "Build manifest: ${manifest}"
log "Image: ${image_ref}"
log "Common JAR SHA-256: ${common_jar_hash}"

if [[ "${INCLUDE_GATEWAY}" == "true" ]]; then
  gateway_group="$(pom_value "${GATEWAY_LIBRARY_SOURCE}" project.groupId)"
  gateway_artifact="$(pom_value "${GATEWAY_LIBRARY_SOURCE}" project.artifactId)"
  gateway_version="$(pom_value "${GATEWAY_LIBRARY_SOURCE}" project.version)"
  gateway_revision="$(git_revision "${GATEWAY_LIBRARY_SOURCE}")"
  gateway_image_revision="$(git_revision "${GATEWAY_IMAGE_SOURCE}")"
  gateway_dependency_dir="${GATEWAY_IMAGE_SOURCE}/target/dependency"
  mapfile -t gateway_common_jars < <(find "${gateway_dependency_dir}" -maxdepth 1 -type f -name "${common_artifact}-*.jar" -print)
  mapfile -t gateway_jars < <(find "${gateway_dependency_dir}" -maxdepth 1 -type f -name "${gateway_artifact}-*.jar" -print)
  [[ "${#gateway_common_jars[@]}" -eq 1 ]] || die "Expected exactly one ${common_artifact} JAR in GW, found ${#gateway_common_jars[@]}"
  [[ "${#gateway_jars[@]}" -eq 1 ]] || die "Expected exactly one ${gateway_artifact} JAR in GW, found ${#gateway_jars[@]}"
  gateway_common_hash="$(sha256sum "${gateway_common_jars[0]}" | awk '{print $1}')"
  [[ "${gateway_common_hash}" == "${common_jar_hash}" ]] || die "GW and OrderSvr contain different com.app.common JARs"
  gateway_jar_hash="$(sha256sum "${gateway_jars[0]}" | awk '{print $1}')"
  gateway_image_ref="${GATEWAY_IMAGE_REPOSITORY}:cluster-dev-${gateway_image_revision}-gateway-${gateway_revision}-common-${common_revision}"

  if [[ "${SKIP_DOCKER_BUILD}" != "true" ]]; then
    log "Building immutable development image ${gateway_image_ref}"
    docker build \
      --build-arg REPO_URL=https://github.com/bliplink/gw \
      --build-arg SERVICE_REVISION="${gateway_image_revision}" \
      --build-arg GATEWAY_REVISION="${gateway_revision}" \
      --build-arg COMMON_REVISION="${common_revision}" \
      --build-arg COMMON_GAV="${common_gav}" \
      --build-arg BUILD_DATE="${build_date}" \
      --label dc.common.jar.sha256="${gateway_common_hash}" \
      --label dc.gateway.jar.sha256="${gateway_jar_hash}" \
      --tag "${gateway_image_ref}" \
      "${GATEWAY_IMAGE_SOURCE}"
  fi

  gateway_manifest="${SCRIPT_DIR}/.cluster-dev/gw-build-manifest.env"
  {
    printf 'BUILD_DATE=%s\n' "${build_date}"
    printf 'BUILD_OUTPUT_TIMESTAMP=%s\n' "${build_output_timestamp}"
    printf 'GW_IMAGE=%s\n' "${gateway_image_ref}"
    printf 'GW_WRAPPER_REVISION=%s\n' "${gateway_image_revision}"
    printf 'GATEWAY_GAV=%s\n' "${gateway_group}:${gateway_artifact}:${gateway_version}"
    printf 'GATEWAY_REVISION=%s\n' "${gateway_revision}"
    printf 'GATEWAY_JAR_SHA256=%s\n' "${gateway_jar_hash}"
    printf 'COMMON_GAV=%s\n' "${common_gav}"
    printf 'COMMON_REVISION=%s\n' "${common_revision}"
    printf 'COMMON_JAR_SHA256=%s\n' "${gateway_common_hash}"
  } > "${gateway_manifest}"
  log "GW build manifest: ${gateway_manifest}"
  log "GW image: ${gateway_image_ref}"
fi

if [[ "${INCLUDE_CORE_CONSUMERS}" == "true" ]]; then
  consumer_manifest="${SCRIPT_DIR}/.cluster-dev/order-cluster-consumer-build-manifest.env"
  : > "${consumer_manifest}"
  printf 'BUILD_DATE=%s\nCOMMON_REVISION=%s\nCOMMON_JAR_SHA256=%s\n' \
    "${build_date}" "${common_revision}" "${common_jar_hash}" >> "${consumer_manifest}"
  while IFS='|' read -r service source repository repo_url; do
    revision="$(git_revision "${source}")"
    dependency_dir="${source}/target/dependency"
    mapfile -t embedded_common < <(find "${dependency_dir}" -maxdepth 1 -type f -name "${common_artifact}-*.jar" -print)
    [[ "${#embedded_common[@]}" -eq 1 ]] ||
      die "Expected exactly one ${common_artifact} JAR in ${service}, found ${#embedded_common[@]}"
    embedded_hash="$(sha256sum "${embedded_common[0]}" | awk '{print $1}')"
    [[ "${embedded_hash}" == "${common_jar_hash}" ]] ||
      die "${service} and OrderSvr contain different com.app.common JARs"
    consumer_image="${repository}:cluster-dev-${revision}-common-${common_revision}"
    if [[ "${SKIP_DOCKER_BUILD}" != "true" ]]; then
      log "Building immutable development image ${consumer_image}"
      docker build \
        --build-arg REPO_URL="${repo_url}" \
        --label dc.service.revision="${revision}" \
        --label dc.common.revision="${common_revision}" \
        --label dc.common.gav="${common_gav}" \
        --label dc.common.jar.sha256="${common_jar_hash}" \
        --label dc.dc-common.revision="${dc_revision}" \
        --label dc.dc-common.jar.sha256="${dc_jar_hash}" \
        --tag "${consumer_image}" "${source}"
      if [[ "${PUSH_IMAGES}" == "true" ]]; then
        log "Pushing ${consumer_image}"
        docker push "${consumer_image}"
      fi
    fi
    printf '%s_IMAGE=%s\n%s_REVISION=%s\n' \
      "${service^^}" "${consumer_image}" "${service^^}" "${revision}" >> "${consumer_manifest}"
    log "${service} image: ${consumer_image}"
  done <<EOF
ProjectionSvr|${PROJECTIONSVR_SOURCE}|${PROJECTIONSVR_IMAGE_REPOSITORY}|https://github.com/bliplink/com-app-dc-projectionsvr
MDSvr|${MDSVR_SOURCE}|${MDSVR_IMAGE_REPOSITORY}|https://github.com/bliplink/com.app.dc.mdsvr
TradeSvr|${TRADESVR_SOURCE}|${TRADESVR_IMAGE_REPOSITORY}|https://github.com/bliplink/com.app.dc.tradesvr
LiqSvr|${LIQSVR_SOURCE}|${LIQSVR_IMAGE_REPOSITORY}|https://github.com/bliplink/com.app.dc.liqsvr
EOF
  log "Core consumer manifest: ${consumer_manifest}"
fi

if [[ "${PUSH_IMAGES}" == "true" && "${SKIP_DOCKER_BUILD}" != "true" ]]; then
  log "Pushing ${image_ref}"
  docker push "${image_ref}"
  if [[ "${INCLUDE_GATEWAY}" == "true" ]]; then
    log "Pushing ${gateway_image_ref}"
    docker push "${gateway_image_ref}"
  fi
fi
