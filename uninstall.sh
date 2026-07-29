#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"
OVERRIDE_FILE="${ROOT_DIR}/compose.override.generated.yaml"
MANAGED_MARKER=".dc-quant-deploy-managed"

PROJECT_CONTAINERS=(
  dc-web
  dc-batchsvr
  dc-simsvr
  dc-indsvr
  dc-quantsvr
  dc-apssvr
  dc-mdsvr
  dc-loginsvr
  dc-gateway
  dc-zookeeper
  dc-clickhouse
)

usage() {
  cat <<'USAGE'
Usage:
  sudo ./uninstall.sh
  sudo ./uninstall.sh --keep-images

Remove only resources created by dc-quant-deploy:
  - dc-* containers
  - Compose networks and volumes owned by this project
  - project images, unless --keep-images is used
  - DEPLOY_ROOT, including ClickHouse data, logs, and runtime configuration
  - generated deployment files in this repository

Docker itself, host nginx, host ZooKeeper, unrelated containers, and this Git
repository are preserved.
USAGE
}

KEEP_IMAGES=false

parse_args() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --keep-images)
        KEEP_IMAGES=true
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done
}

load_env() {
  DEPLOY_ROOT="/opt/dc-runtime"
  COMPOSE_PROJECT_NAME="dc-quant-deploy"
  if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    set -a && . "${ENV_FILE}" && set +a
  fi
}

validate_runtime_root() {
  [[ "${DEPLOY_ROOT}" == /* ]] || {
    echo "DEPLOY_ROOT must be an absolute path: ${DEPLOY_ROOT}" >&2
    exit 1
  }

  case "${DEPLOY_ROOT}" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var|/opt/sumscope)
      echo "Refusing to remove protected path: ${DEPLOY_ROOT}" >&2
      exit 1
      ;;
  esac

  if [[ "${DEPLOY_ROOT}" != "/opt/dc-runtime" &&
        ! -f "${DEPLOY_ROOT}/${MANAGED_MARKER}" ]]; then
    echo "Refusing to remove an unmarked custom DEPLOY_ROOT: ${DEPLOY_ROOT}" >&2
    echo "Expected marker: ${DEPLOY_ROOT}/${MANAGED_MARKER}" >&2
    exit 1
  fi
}

compose() {
  local args=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
  if [[ -f "${OVERRIDE_FILE}" ]]; then
    args+=(-f "${OVERRIDE_FILE}")
  fi
  args+=(--profile embedded-clickhouse)
  "${args[@]}" "$@"
}

append_unique() {
  local value="$1"
  local existing
  [[ -n "${value}" ]] || return 0
  for existing in "${IMAGE_REFS[@]:-}"; do
    [[ "${existing}" == "${value}" ]] && return 0
  done
  IMAGE_REFS+=("${value}")
}

collect_project_images() {
  local container image
  IMAGE_REFS=()

  if [[ -f "${ENV_FILE}" && -f "${COMPOSE_FILE}" ]]; then
    while IFS= read -r image; do
      append_unique "${image}"
    done < <(compose config --images 2>/dev/null || true)
  fi

  for container in "${PROJECT_CONTAINERS[@]}"; do
    image="$(docker inspect --format '{{.Config.Image}}' "${container}" 2>/dev/null || true)"
    append_unique "${image}"
  done
}

remove_compose_resources() {
  local resource

  if [[ -f "${ENV_FILE}" && -f "${COMPOSE_FILE}" ]]; then
    compose down --remove-orphans --volumes --timeout 30 || true
  fi

  for resource in "${PROJECT_CONTAINERS[@]}"; do
    docker rm -f "${resource}" >/dev/null 2>&1 || true
  done

  while IFS= read -r resource; do
    [[ -n "${resource}" ]] && docker network rm "${resource}" >/dev/null 2>&1 || true
  done < <(
    docker network ls \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.ID}}'
  )

  while IFS= read -r resource; do
    [[ -n "${resource}" ]] && docker volume rm "${resource}" >/dev/null 2>&1 || true
  done < <(
    docker volume ls \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Name}}'
  )
}

remove_project_images() {
  local image
  [[ "${KEEP_IMAGES}" == "false" ]] || return 0

  for image in "${IMAGE_REFS[@]:-}"; do
    docker image rm "${image}" >/dev/null 2>&1 || true
  done
}

remove_runtime_data() {
  if [[ -e "${DEPLOY_ROOT}" ]]; then
    rm -rf --one-file-system -- "${DEPLOY_ROOT}"
  fi
}

remove_generated_repository_files() {
  rm -f -- \
    "${ENV_FILE}" \
    "${ROOT_DIR}"/.env.prod.bak* \
    "${ROOT_DIR}/.last_backup" \
    "${ROOT_DIR}/.compose.config.check.yaml" \
    "${OVERRIDE_FILE}"
  rm -rf -- \
    "${ROOT_DIR}/backups" \
    "${ROOT_DIR}/.fresh_install_backup" \
    "${ROOT_DIR}/.external_rehearsal_backup" \
    "${ROOT_DIR}/control.prod/ATSConfig.ini" \
    "${ROOT_DIR}/control.prod/DBPoolConfig.ini" \
    "${ROOT_DIR}/control.prod/overrides"
}

verify_removed() {
  local container failed=0

  for container in "${PROJECT_CONTAINERS[@]}"; do
    if docker container inspect "${container}" >/dev/null 2>&1; then
      echo "Container still exists: ${container}" >&2
      failed=1
    fi
  done

  if [[ -e "${DEPLOY_ROOT}" ]]; then
    echo "Runtime directory still exists: ${DEPLOY_ROOT}" >&2
    failed=1
  fi

  if docker network ls \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.ID}}' | grep -q .; then
    echo "Project network still exists." >&2
    failed=1
  fi

  if docker volume ls \
      --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
      --format '{{.Name}}' | grep -q .; then
    echo "Project volume still exists." >&2
    failed=1
  fi

  return "${failed}"
}

main() {
  parse_args "$@"
  [[ "$(id -u)" -eq 0 ]] || {
    echo "Run this command as root or with sudo." >&2
    exit 1
  }
  command -v docker >/dev/null 2>&1 || {
    echo "Docker is not installed; only generated files can be removed manually." >&2
    exit 1
  }

  load_env
  validate_runtime_root
  collect_project_images

  echo "Removing dc-quant-deploy runtime from ${DEPLOY_ROOT}."
  remove_compose_resources
  remove_project_images
  remove_runtime_data
  remove_generated_repository_files
  verify_removed

  echo "dc-quant-deploy was removed successfully."
  echo "The Git repository and shared host software were preserved."
}

main "$@"
