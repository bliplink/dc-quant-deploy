#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.prod}"
DEPLOY_SCRIPT="${SAAS_AUTO_UPDATE_DEPLOY_SCRIPT:-${SCRIPT_DIR}/deploy-saas.sh}"
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
LOCK_FILE="${SAAS_AUTO_UPDATE_LOCK_FILE:-/tmp/dc-saas-auto-update.lock}"

DRY_RUN="false"
FORCE="false"
SKIP_GIT_UPDATE="false"

APP_SERVICES=(
  gateway loginsvr mdsvr apssvr ordersvr tradesvr liqsvr managersvr adminsvr web
)

log() {
  printf '[%s] [saas-auto-update] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: sudo ./auto-update-saas.sh [--dry-run] [--force] [--skip-git-update]

Checks the configured public GHCR tags without pulling image layers. When the
complete application digest set has remained stable for the configured quiet
window, all changed images are pulled serially and deployed as one release.

Options:
  --dry-run          Show the detected release without pulling or changing state.
  --force            Bypass the quiet window and retry backoff.
  --skip-git-update  Do not fast-forward this deployment repository first.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN="true"
      ;;
    --force)
      FORCE="true"
      ;;
    --skip-git-update)
      SKIP_GIT_UPDATE="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
  shift
done

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_file() {
  [[ -f "$1" ]] || die "Missing required file: $1"
}

positive_integer() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 > 0 ))
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

service_image_ref() {
  case "$1" in
    gateway) echo "${GW_IMAGE_REPOSITORY}:${GW_TAG}" ;;
    loginsvr) echo "${LOGINSVR_IMAGE_REPOSITORY}:${LOGINSVR_TAG}" ;;
    mdsvr) echo "${MDSVR_IMAGE_REPOSITORY}:${MDSVR_TAG}" ;;
    apssvr) echo "${APSSVR_IMAGE_REPOSITORY}:${APSSVR_TAG}" ;;
    ordersvr) echo "${ORDERSVR_IMAGE_REPOSITORY}:${ORDERSVR_TAG}" ;;
    tradesvr) echo "${TRADESVR_IMAGE_REPOSITORY}:${TRADESVR_TAG}" ;;
    liqsvr) echo "${LIQSVR_IMAGE_REPOSITORY}:${LIQSVR_TAG}" ;;
    managersvr) echo "${MANAGERSVR_IMAGE_REPOSITORY}:${MANAGERSVR_TAG}" ;;
    adminsvr) echo "${ADMINSVR_IMAGE_REPOSITORY}:${ADMINSVR_TAG}" ;;
    web) echo "${TRADE_WEB_IMAGE_REPOSITORY}:${TRADE_WEB_TAG}" ;;
    *) return 1 ;;
  esac
}

service_container_name() {
  case "$1" in
    gateway) echo "dc-saas-gateway" ;;
    web) echo "dc-saas-trade-web" ;;
    loginsvr|mdsvr|apssvr|ordersvr|tradesvr|liqsvr|managersvr|adminsvr)
      echo "dc-saas-$1"
      ;;
    *) return 1 ;;
  esac
}

running_image_id() {
  docker inspect "$1" --format '{{.Image}}' 2>/dev/null || true
}

local_image_id() {
  docker image inspect "$1" --format '{{.Id}}' 2>/dev/null || true
}

curl_with_retry() {
  local attempt
  for attempt in 1 2; do
    if timeout --signal=TERM --kill-after=5 "${MANIFEST_TIMEOUT_SECONDS}" \
      curl -fsSL --connect-timeout 10 --max-time "${MANIFEST_TIMEOUT_SECONDS}" "$@"; then
      return 0
    fi
    log "Registry request failed (attempt ${attempt}/2)." >&2
    sleep $((attempt * 3))
  done
  return 1
}

ghcr_remote_digest() {
  local image_ref="$1"
  local without_host repository tag token_json token headers digest

  [[ "${image_ref}" == ghcr.io/* ]] || {
    log "Only public ghcr.io application images support automatic digest checks: ${image_ref}" >&2
    return 1
  }
  [[ "${image_ref}" != *@* ]] || {
    log "Digest-pinned images are immutable and cannot be auto-updated: ${image_ref}" >&2
    return 1
  }

  without_host="${image_ref#ghcr.io/}"
  [[ "${without_host}" == *:* ]] || {
    log "Application image must include an explicit tag: ${image_ref}" >&2
    return 1
  }
  repository="${without_host%:*}"
  tag="${without_host##*:}"
  [[ -n "${repository}" && -n "${tag}" ]] || return 1

  token_json="$(curl_with_retry \
    "https://ghcr.io/token?service=ghcr.io&scope=repository:${repository}:pull")" || return 1
  token="$(printf '%s' "${token_json}" | sed -n \
    's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
  [[ -n "${token}" ]] || {
    log "GHCR did not return a public pull token for ${repository}." >&2
    return 1
  }

  headers="$(curl_with_retry -D - -o /dev/null \
    -H "Authorization: Bearer ${token}" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "https://ghcr.io/v2/${repository}/manifests/${tag}")" || return 1
  unset token token_json

  digest="$(printf '%s\n' "${headers}" | tr -d '\r' | awk '
    tolower($1) == "docker-content-digest:" { value=$2 }
    END { print value }
  ')"
  [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    log "GHCR returned no valid manifest digest for ${image_ref}." >&2
    return 1
  }
  printf '%s\n' "${digest}"
}

record_failure() {
  local reason="$1"
  local count=0 backoff next_epoch index
  if [[ -f "${FAILURE_FILE}" ]]; then
    count="$(awk -F= '$1 == "count" { print $2 }' "${FAILURE_FILE}" 2>/dev/null || true)"
  fi
  [[ "${count}" =~ ^[0-9]+$ ]] || count=0
  count=$((count + 1))
  backoff="${FAILURE_BACKOFF_SECONDS}"
  for ((index=1; index<count; index++)); do
    if (( backoff >= FAILURE_MAX_BACKOFF_SECONDS / 2 )); then
      backoff="${FAILURE_MAX_BACKOFF_SECONDS}"
      break
    fi
    backoff=$((backoff * 2))
  done
  (( backoff <= FAILURE_MAX_BACKOFF_SECONDS )) || backoff="${FAILURE_MAX_BACKOFF_SECONDS}"
  next_epoch=$(( $(date +%s) + backoff ))
  {
    printf 'count=%s\n' "${count}"
    printf 'next_epoch=%s\n' "${next_epoch}"
    printf 'reason=%s\n' "${reason//[^a-zA-Z0-9_.:-]/_}"
  } > "${FAILURE_FILE}.tmp"
  mv "${FAILURE_FILE}.tmp" "${FAILURE_FILE}"
  log "Failure backoff is ${backoff}s (failure count=${count}, reason=${reason})."
}

backoff_is_active() {
  local next_epoch now
  [[ -f "${FAILURE_FILE}" ]] || return 1
  next_epoch="$(awk -F= '$1 == "next_epoch" { print $2 }' "${FAILURE_FILE}" 2>/dev/null || true)"
  [[ "${next_epoch}" =~ ^[0-9]+$ ]] || return 1
  now="$(date +%s)"
  if (( now < next_epoch )); then
    log "Previous failure is in backoff until epoch ${next_epoch}; skip this run."
    return 0
  fi
  return 1
}

update_deploy_repository() {
  local old_head new_head dirty
  [[ "${AUTO_UPDATE_DEPLOY_REPO}" == "true" ]] || return 0
  [[ "${SKIP_GIT_UPDATE}" == "false" ]] || {
    log "Deployment repository update skipped by command line."
    return 0
  }
  [[ "${DRY_RUN}" == "false" ]] || {
    log "Dry run: deployment repository fetch is skipped."
    return 0
  }
  [[ -d "${SCRIPT_DIR}/.git" ]] || {
    log "Deployment repository update is enabled but ${SCRIPT_DIR} is not a Git worktree." >&2
    return 1
  }

  dirty="$(git -C "${SCRIPT_DIR}" status --porcelain --untracked-files=no)"
  [[ -z "${dirty}" ]] || {
    log "Tracked deployment files are dirty; refusing automatic fast-forward." >&2
    return 1
  }
  old_head="$(git -C "${SCRIPT_DIR}" rev-parse HEAD)"
  log "Checking deployment branch origin/${AUTO_UPDATE_DEPLOY_BRANCH}."
  if ! timeout --signal=TERM --kill-after=10 "${GIT_TIMEOUT_SECONDS}" \
    git -C "${SCRIPT_DIR}" -c http.version=HTTP/1.1 fetch origin "${AUTO_UPDATE_DEPLOY_BRANCH}"; then
    log "Deployment repository fetch failed." >&2
    return 1
  fi
  if ! git -C "${SCRIPT_DIR}" merge --ff-only FETCH_HEAD; then
    log "Deployment repository cannot be fast-forwarded safely." >&2
    return 1
  fi
  new_head="$(git -C "${SCRIPT_DIR}" rev-parse HEAD)"
  if [[ "${old_head}" != "${new_head}" ]]; then
    log "Deployment repository advanced ${old_head:0:12} -> ${new_head:0:12}."
  fi
}

rollback_images() {
  local service image_ref previous_id
  [[ -f "${ROLLBACK_FILE}" ]] || return 1
  log "Restoring image tags used by the previous running containers."
  while IFS='|' read -r service image_ref previous_id; do
    [[ -n "${service}" && -n "${image_ref}" && -n "${previous_id}" ]] || continue
    if ! docker image inspect "${previous_id}" >/dev/null 2>&1; then
      log "Rollback image is missing for ${service}: ${previous_id}" >&2
      return 1
    fi
    docker tag "${previous_id}" "${image_ref}"
  done < "${ROLLBACK_FILE}"
}

main() {
  local service image_ref container remote_digest fingerprint now first_seen age
  local last_digest current_running_id current_local_id release_changed runtime_drift
  local deploy_needed
  local -a changed_services=()

  [[ "${EUID}" -eq 0 ]] || die "Run as root or with sudo."
  require_file "${ENV_FILE}"
  require_file "${COMPOSE_FILE}"
  require_file "${DEPLOY_SCRIPT}"
  for command in docker curl sed awk tr timeout flock sha256sum git cmp; do
    require_command "${command}"
  done

  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a

  [[ "${IMAGE_SOURCE:-registry}" == "registry" ]] ||
    die "Automatic image deployment requires IMAGE_SOURCE=registry."
  : "${DEPLOY_ROOT:?DEPLOY_ROOT is required}"

  STATE_DIR="${SAAS_AUTO_UPDATE_STATE_DIR:-${DEPLOY_ROOT}/auto-update}"
  LAST_SUCCESS_FILE="${STATE_DIR}/last-successful.digestset"
  PENDING_FILE="${STATE_DIR}/pending.digestset"
  PENDING_SINCE_FILE="${STATE_DIR}/pending.first-seen-epoch"
  FAILURE_FILE="${STATE_DIR}/failure.state"
  ROLLBACK_FILE="${STATE_DIR}/rollback.images"
  HISTORY_FILE="${STATE_DIR}/last-successful.meta"

  QUIET_SECONDS="${SAAS_AUTO_UPDATE_QUIET_SECONDS:-300}"
  PULL_TIMEOUT_SECONDS="${SAAS_AUTO_UPDATE_PULL_TIMEOUT_SECONDS:-600}"
  MANIFEST_TIMEOUT_SECONDS="${SAAS_AUTO_UPDATE_MANIFEST_TIMEOUT_SECONDS:-30}"
  GIT_TIMEOUT_SECONDS="${SAAS_AUTO_UPDATE_GIT_TIMEOUT_SECONDS:-180}"
  FAILURE_BACKOFF_SECONDS="${SAAS_AUTO_UPDATE_FAILURE_BACKOFF_SECONDS:-600}"
  FAILURE_MAX_BACKOFF_SECONDS="${SAAS_AUTO_UPDATE_FAILURE_MAX_BACKOFF_SECONDS:-21600}"
  AUTO_UPDATE_DEPLOY_REPO="${SAAS_AUTO_UPDATE_DEPLOY_REPO:-true}"
  AUTO_UPDATE_DEPLOY_BRANCH="${SAAS_AUTO_UPDATE_DEPLOY_BRANCH:-saas-crypto}"

  for value in QUIET_SECONDS PULL_TIMEOUT_SECONDS MANIFEST_TIMEOUT_SECONDS GIT_TIMEOUT_SECONDS FAILURE_BACKOFF_SECONDS FAILURE_MAX_BACKOFF_SECONDS; do
    positive_integer "${!value}" || die "${value} must be a positive integer."
  done

  install -d -m 0750 "${STATE_DIR}"
  exec 9>"${LOCK_FILE}"
  if ! flock -n 9; then
    log "Another SaaS deploy or auto-update run holds ${LOCK_FILE}; skip."
    exit 0
  fi

  if [[ "${FORCE}" == "false" ]] && backoff_is_active; then
    exit 0
  fi

  if ! update_deploy_repository; then
    record_failure "deploy-repository-update"
    exit 1
  fi

  compose config --quiet

  REMOTE_FILE="$(mktemp "${STATE_DIR}/remote.XXXXXX")"
  trap 'rm -f "${REMOTE_FILE:-}" "${ROLLBACK_FILE}.tmp"' EXIT

  log "Checking public application image digests."
  for service in "${APP_SERVICES[@]}"; do
    image_ref="$(service_image_ref "${service}")"
    if ! remote_digest="$(ghcr_remote_digest "${image_ref}")"; then
      record_failure "manifest-${service}"
      exit 1
    fi
    printf '%s|%s|%s\n' "${service}" "${image_ref}" "${remote_digest}" >> "${REMOTE_FILE}"
    log "${service}: ${remote_digest}"
  done
  fingerprint="$(sha256sum "${REMOTE_FILE}" | awk '{print $1}')"

  release_changed="true"
  if [[ -f "${LAST_SUCCESS_FILE}" ]] && cmp -s "${REMOTE_FILE}" "${LAST_SUCCESS_FILE}"; then
    release_changed="false"
  fi

  runtime_drift="false"
  for service in "${APP_SERVICES[@]}"; do
    image_ref="$(service_image_ref "${service}")"
    container="$(service_container_name "${service}")"
    current_running_id="$(running_image_id "${container}")"
    current_local_id="$(local_image_id "${image_ref}")"
    if [[ -z "${current_running_id}" || -z "${current_local_id}" || "${current_running_id}" != "${current_local_id}" ]]; then
      runtime_drift="true"
    fi
  done

  if [[ "${release_changed}" == "false" && "${runtime_drift}" == "false" ]]; then
    rm -f "${PENDING_FILE}" "${PENDING_SINCE_FILE}" "${FAILURE_FILE}"
    log "All running SaaS containers already use the recorded release ${fingerprint}."
    exit 0
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "Dry run: release_changed=${release_changed}, runtime_drift=${runtime_drift}, fingerprint=${fingerprint}."
    exit 0
  fi

  if [[ "${release_changed}" == "true" && "${FORCE}" == "false" ]]; then
    now="$(date +%s)"
    if [[ ! -f "${PENDING_FILE}" ]] || ! cmp -s "${REMOTE_FILE}" "${PENDING_FILE}"; then
      cp "${REMOTE_FILE}" "${PENDING_FILE}.tmp"
      mv "${PENDING_FILE}.tmp" "${PENDING_FILE}"
      printf '%s\n' "${now}" > "${PENDING_SINCE_FILE}.tmp"
      mv "${PENDING_SINCE_FILE}.tmp" "${PENDING_SINCE_FILE}"
      log "Detected release ${fingerprint}; waiting ${QUIET_SECONDS}s for all CI images to settle."
      exit 0
    fi
    first_seen="$(cat "${PENDING_SINCE_FILE}" 2>/dev/null || echo "${now}")"
    [[ "${first_seen}" =~ ^[0-9]+$ ]] || first_seen="${now}"
    age=$((now - first_seen))
    if (( age < QUIET_SECONDS )); then
      log "Release ${fingerprint} has been stable for ${age}s; quiet window is ${QUIET_SECONDS}s."
      exit 0
    fi
  fi

  : > "${ROLLBACK_FILE}.tmp"
  for service in "${APP_SERVICES[@]}"; do
    image_ref="$(service_image_ref "${service}")"
    container="$(service_container_name "${service}")"
    remote_digest="$(awk -F'|' -v name="${service}" '$1 == name { print $3 }' "${REMOTE_FILE}")"
    last_digest=""
    if [[ -f "${LAST_SUCCESS_FILE}" ]]; then
      last_digest="$(awk -F'|' -v name="${service}" '$1 == name { print $3 }' "${LAST_SUCCESS_FILE}")"
    fi
    current_running_id="$(running_image_id "${container}")"
    current_local_id="$(local_image_id "${image_ref}")"
    if [[ "${remote_digest}" != "${last_digest}" || -z "${current_running_id}" || -z "${current_local_id}" || "${current_running_id}" != "${current_local_id}" ]]; then
      changed_services+=("${service}")
      printf '%s|%s|%s\n' "${service}" "${image_ref}" "${current_running_id}" >> "${ROLLBACK_FILE}.tmp"
    fi
  done
  mv "${ROLLBACK_FILE}.tmp" "${ROLLBACK_FILE}"

  log "Release ${fingerprint} is ready; changed services: ${changed_services[*]}."
  for service in "${changed_services[@]}"; do
    image_ref="$(service_image_ref "${service}")"
    log "Pulling ${service} serially: ${image_ref}"
    if ! timeout --signal=TERM --kill-after=30 "${PULL_TIMEOUT_SECONDS}" docker pull "${image_ref}"; then
      record_failure "pull-${service}"
      exit 1
    fi
    [[ -n "$(local_image_id "${image_ref}")" ]] || {
      record_failure "missing-local-image-${service}"
      exit 1
    }
  done

  deploy_needed="false"
  for service in "${changed_services[@]}"; do
    image_ref="$(service_image_ref "${service}")"
    container="$(service_container_name "${service}")"
    if [[ "$(running_image_id "${container}")" != "$(local_image_id "${image_ref}")" ]]; then
      deploy_needed="true"
    fi
  done

  if [[ "${deploy_needed}" == "true" ]]; then
    log "Applying migrations and recreating changed containers as one SaaS release."
    if ! SAAS_DEPLOY_LOCK_HELD=true COMPOSE_PULL_PARALLEL_LIMIT=1 COMPOSE_UP_PARALLEL_LIMIT=1 \
      "${DEPLOY_SCRIPT}" --skip-host-prepare --skip-pull; then
      log "New release validation failed; starting image rollback." >&2
      if rollback_images && SAAS_DEPLOY_LOCK_HELD=true COMPOSE_PULL_PARALLEL_LIMIT=1 COMPOSE_UP_PARALLEL_LIMIT=1 \
        "${DEPLOY_SCRIPT}" --skip-host-prepare --skip-pull; then
        log "Previous application images were restored successfully." >&2
      else
        log "CRITICAL: automatic rollback did not restore a healthy SaaS stack." >&2
      fi
      record_failure "deploy-or-validation"
      exit 1
    fi
  else
    log "Remote digest changed but all pulled images resolve to the running image IDs; no restart required."
  fi

  cp "${REMOTE_FILE}" "${LAST_SUCCESS_FILE}.tmp"
  mv "${LAST_SUCCESS_FILE}.tmp" "${LAST_SUCCESS_FILE}"
  {
    printf 'deployed_at=%s\n' "$(date --iso-8601=seconds)"
    printf 'fingerprint=%s\n' "${fingerprint}"
    printf 'git_commit=%s\n' "$(git -C "${SCRIPT_DIR}" rev-parse HEAD 2>/dev/null || echo unavailable)"
    printf 'services=%s\n' "${changed_services[*]}"
  } > "${HISTORY_FILE}.tmp"
  mv "${HISTORY_FILE}.tmp" "${HISTORY_FILE}"
  rm -f "${PENDING_FILE}" "${PENDING_SINCE_FILE}" "${FAILURE_FILE}" "${ROLLBACK_FILE}"
  log "SaaS release ${fingerprint} deployed and validated successfully."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
