#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/.env.prod}"

log() {
  printf '[saas-build] %s\n' "$*"
}

die() {
  printf '[saas-build] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || die "Cannot read ${ENV_FILE}"
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

BUILD_ROOT="${BUILD_ROOT:-/data/dc-saas-build}"
MAVEN_BUILD_IMAGE="${MAVEN_BUILD_IMAGE:-docker.m.daocloud.io/library/maven:3.9.9-eclipse-temurin-8}"
SRC_ROOT="${BUILD_ROOT}/src"
M2_ROOT="${BUILD_ROOT}/m2"
SOURCE_BUNDLE_PATH="${SOURCE_BUNDLE_PATH:-${BUILD_ROOT}/source-bundle.tar.gz}"
SOURCE_BUNDLE_SHA256="${SOURCE_BUNDLE_SHA256:-}"

[[ "${BUILD_ROOT}" == /* && "${BUILD_ROOT}" != "/" && "${BUILD_ROOT}" != "/opt" ]] ||
  die "BUILD_ROOT must be a dedicated absolute directory."

install -d -m 0750 "${SRC_ROOT}" "${M2_ROOT}"

prepare_source_bundle() {
  local entry actual_hash resolved_src

  [[ -f "${SRC_ROOT}/.source-bundle" ]] && return 0
  [[ -f "${SOURCE_BUNDLE_PATH}" ]] || return 0
  [[ "${SOURCE_BUNDLE_PATH}" == /* ]] ||
    die "SOURCE_BUNDLE_PATH must be an absolute path."

  if [[ -n "${SOURCE_BUNDLE_SHA256}" ]]; then
    actual_hash="$(sha256sum -- "${SOURCE_BUNDLE_PATH}" | awk '{print $1}')"
    [[ "${actual_hash,,}" == "${SOURCE_BUNDLE_SHA256,,}" ]] ||
      die "Source bundle SHA-256 does not match SOURCE_BUNDLE_SHA256."
  fi

  while IFS= read -r entry; do
    [[ "${entry}" == src || "${entry}" == src/* ]] ||
      die "Source bundle contains a path outside src/: ${entry}"
    [[ "/${entry}/" != *"/../"* ]] ||
      die "Source bundle contains a parent-directory path: ${entry}"
  done < <(tar -tzf "${SOURCE_BUNDLE_PATH}")

  resolved_src="$(readlink -m "${SRC_ROOT}")"
  [[ "${resolved_src}" == "${BUILD_ROOT}/src" ]] ||
    die "Refusing to replace unexpected source directory ${resolved_src}."

  log "Extracting verified private source bundle ${SOURCE_BUNDLE_PATH}."
  rm -rf -- "${SRC_ROOT}"
  tar -xzf "${SOURCE_BUNDLE_PATH}" -C "${BUILD_ROOT}"
  [[ -f "${SRC_ROOT}/.source-bundle" ]] ||
    die "Source bundle does not contain src/.source-bundle."
}

prepare_source_bundle

sync_repo() {
  local name="$1"
  local url="$2"
  local branch="$3"
  local target="${SRC_ROOT}/${name}"

  if [[ -f "${SRC_ROOT}/.source-bundle" ]]; then
    [[ -d "${target}" ]] || die "Uploaded source bundle is missing ${name}."
    log "Using uploaded source for ${name}."
    return 0
  fi

  if [[ -d "${target}/.git" ]]; then
    log "Updating ${name} from ${branch}."
    git -C "${target}" fetch --depth 1 origin "${branch}"
    git -C "${target}" checkout -B saas-build FETCH_HEAD
  else
    log "Cloning ${name} from ${branch}."
    git clone --depth 1 --branch "${branch}" "${url}" "${target}"
  fi
}

run_maven() {
  local source_dir="$1"
  shift
  docker run --rm --memory=3g -e MAVEN_OPTS="-Xms64m -Xmx1024m -XX:+UseSerialGC" -v "${M2_ROOT}:/root/.m2:Z" -v "${source_dir}:/workspace:Z" -w /workspace "${MAVEN_BUILD_IMAGE}" mvn -B -U "$@"
}

build_java_image() {
  local source_name="$1"
  local image_ref="$2"
  local source_dir="${SRC_ROOT}/${source_name}"
  log "Building Java service ${source_name}."
  run_maven "${source_dir}" clean package dependency:copy-dependencies -DskipTests -DoutputDirectory=target/dependency
  DOCKER_BUILDKIT=1 docker build --pull -t "${image_ref}" "${source_dir}"
}

sync_repo common https://github.com/bliplink/com.app.dc.git saas-crypto
sync_repo connector https://github.com/bliplink/binance-futures-connector.git main
sync_repo ordersvr https://github.com/bliplink/com.app.dc.ordersvr.git saas-crypto
sync_repo tradesvr https://github.com/bliplink/com.app.dc.tradesvr.git saas-crypto
sync_repo liqsvr https://github.com/bliplink/com.app.dc.liqsvr.git saas-crypto
sync_repo mdsvr https://github.com/bliplink/com.app.dc.mdsvr.git saas-crypto
sync_repo apssvr https://github.com/bliplink/com.app.dc.apssvr.git saas-crypto
sync_repo loginsvr https://github.com/bliplink/com.app.dc.loginsvr.git saas-crypto
sync_repo managersvr https://github.com/bliplink/com.app.dc.managersvr.git saas-crypto
sync_repo adminsvr https://github.com/bliplink/com.app.dc.adminsvr.git saas-crypto
sync_repo gateway https://github.com/bliplink/gw.git saas-crypto
sync_repo trade-web https://github.com/SKT-Walter/dc-trade-web.git saas-crypto

log "Pulling the reproducible Maven build environment."
docker pull "${MAVEN_BUILD_IMAGE}"

log "Publishing the shared packages into the isolated build cache."
run_maven "${SRC_ROOT}/common" clean install -DskipTests
run_maven "${SRC_ROOT}/connector" clean install -DskipTests

build_java_image ordersvr "${ORDERSVR_IMAGE_REPOSITORY:-dc-saas/ordersvr}:${ORDERSVR_TAG:-saas-crypto}"
build_java_image tradesvr "${TRADESVR_IMAGE_REPOSITORY:-dc-saas/tradesvr}:${TRADESVR_TAG:-saas-crypto}"
build_java_image liqsvr "${LIQSVR_IMAGE_REPOSITORY:-dc-saas/liqsvr}:${LIQSVR_TAG:-saas-crypto}"
build_java_image mdsvr "${MDSVR_IMAGE_REPOSITORY:-dc-saas/mdsvr}:${MDSVR_TAG:-saas-crypto}"
build_java_image apssvr "${APSSVR_IMAGE_REPOSITORY:-dc-saas/apssvr}:${APSSVR_TAG:-saas-crypto}"
build_java_image loginsvr "${LOGINSVR_IMAGE_REPOSITORY:-dc-saas/loginsvr}:${LOGINSVR_TAG:-saas-crypto}"
build_java_image managersvr "${MANAGERSVR_IMAGE_REPOSITORY:-dc-saas/managersvr}:${MANAGERSVR_TAG:-saas-crypto}"
build_java_image adminsvr "${ADMINSVR_IMAGE_REPOSITORY:-dc-saas/adminsvr}:${ADMINSVR_TAG:-saas-crypto}"
build_java_image gateway "${GW_IMAGE_REPOSITORY:-dc-saas/gw}:${GW_TAG:-saas-crypto}"

log "Building dc-trade-web."
DOCKER_BUILDKIT=1 docker build --pull -t "${TRADE_WEB_IMAGE_REPOSITORY:-dc-saas/dc-trade-web}:${TRADE_WEB_TAG:-saas-crypto}" "${SRC_ROOT}/trade-web"

log "All standalone SaaS images are available locally."
