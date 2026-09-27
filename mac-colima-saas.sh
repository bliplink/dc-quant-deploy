#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_CONFIG="${COLIMA_SSH_CONFIG:-${HOME}/.colima/_lima/colima/ssh.config}"
SSH_HOST="${COLIMA_SSH_HOST:-lima-colima}"
REMOTE_REPO="${COLIMA_SAAS_REPO:-${SCRIPT_DIR}}"
WEB_PORTS=(18088 18090 18092)
FORWARD_MARKER="dc-saas-colima-web-forward"

log() { printf '[mac-colima-saas] %s\n' "$*"; }
die() { printf '[mac-colima-saas] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage:
  ./mac-colima-saas.sh forward
  ./mac-colima-saas.sh status
  ./mac-colima-saas.sh install [install-saas.sh args...]
  ./mac-colima-saas.sh uninstall [uninstall-saas.sh args...]
  ./mac-colima-saas.sh reinstall [install-saas.sh args...]
  ./mac-colima-saas.sh acceptance [acceptance-saas.sh args...]

Mac-only wrapper for the Colima development/demo environment.
Linux production hosts should continue using install-saas.sh/uninstall-saas.sh directly.

The wrapper never starts, stops, or reconfigures the Mac v2ray/xray proxy on port 10808.
It owns only localhost forwards for Trade Web 18088, Platform Web 18090, and Tenant Web 18092.
USAGE
}

require_mac() {
  [[ "$(uname -s)" == "Darwin" ]] || die "This helper is only for macOS + Colima."
  [[ -r "${SSH_CONFIG}" ]] || die "Cannot read Colima SSH config: ${SSH_CONFIG}"
  command -v ssh >/dev/null 2>&1 || die "ssh is required."
  command -v curl >/dev/null 2>&1 || die "curl is required."
}

ssh_base() {
  ssh -F "${SSH_CONFIG}" -o ControlMaster=no -o ControlPath=none "$@"
}

remote_shell() {
  local command="$1"
  ssh_base -o ConnectTimeout=8 "${SSH_HOST}" "${command}"
}

quote_args() {
  local out="" arg
  for arg in "$@"; do
    printf -v out '%s %q' "${out}" "${arg}"
  done
  printf '%s' "${out}"
}

port_ready() {
  local port="$1"
  curl --noproxy '*' -fsS --max-time 3 "http://127.0.0.1:${port}/healthz" 2>/dev/null | grep -q '^ok$'
}

ensure_forward() {
  local missing=() port arg pid
  for port in "${WEB_PORTS[@]}"; do
    port_ready "${port}" || missing+=("${port}")
  done
  if [[ "${#missing[@]}" -eq 0 ]]; then
    log "Web forwards already healthy: 18088/18090/18092."
    return 0
  fi

  # Refuse to steal a local port from an unrelated process.
  for port in "${missing[@]}"; do
    if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      die "127.0.0.1:${port} is already owned by another process but does not serve the SaaS health check."
    fi
  done

  local ssh_args=(
    -F "${SSH_CONFIG}"
    -o ControlMaster=no
    -o ControlPath=none
    -o ExitOnForwardFailure=yes
    -o ConnectTimeout=8
    -fN
  )
  for port in "${missing[@]}"; do
    ssh_args+=( -L "127.0.0.1:${port}:127.0.0.1:${port}" )
  done
  ssh_args+=( "${SSH_HOST}" )

  ssh "${ssh_args[@]}"

  for port in "${WEB_PORTS[@]}"; do
    for _ in $(seq 1 20); do
      port_ready "${port}" && break
      sleep 0.25
    done
    port_ready "${port}" || die "Web forward did not become healthy on 127.0.0.1:${port}."
  done
  log "Web forwards ready: Trade=18088 Platform=18090 Tenant=18092."
}

show_status() {
  local port
  printf '%-8s %-10s %s\n' PORT STATE URL
  for port in "${WEB_PORTS[@]}"; do
    if port_ready "${port}"; then
      printf '%-8s %-10s http://127.0.0.1:%s/\n' "${port}" READY "${port}"
    else
      printf '%-8s %-10s http://127.0.0.1:%s/\n' "${port}" DOWN "${port}"
    fi
  done
  if lsof -nP -iTCP:10808 -sTCP:LISTEN >/dev/null 2>&1; then
    log "Mac proxy 10808 listener is present (read-only check; this helper never manages it)."
  else
    log "Mac proxy 10808 listener is absent; this helper will not modify it."
  fi
}

remote_run_script() {
  local script="$1"; shift
  local quoted
  quoted="$(quote_args "$@")"
  remote_shell "cd $(printf '%q' "${REMOTE_REPO}") && sudo -E env ENV_FILE=$(printf '%q' "${REMOTE_REPO}/.env.prod") /bin/bash $(printf '%q' "./${script}")${quoted}"
}

show_credentials() {
  local file="${SCRIPT_DIR}/.default-e2e-credentials.txt"
  if [[ -r "${file}" ]]; then
    printf '\n'
    cat "${file}"
  else
    log "Default E2E credential file is not readable yet: ${file}"
  fi
}

main() {
  require_mac
  local action="${1:-status}"
  [[ "$#" -gt 0 ]] && shift || true
  case "${action}" in
    forward)
      ensure_forward
      show_status
      ;;
    status)
      show_status
      ;;
    install)
      remote_run_script install-saas.sh "$@"
      ensure_forward
      show_credentials
      ;;
    uninstall)
      remote_run_script uninstall-saas.sh "$@"
      log "SaaS containers removed. Existing localhost forward processes are harmless and will fail health checks until reinstall."
      ;;
    reinstall)
      remote_run_script uninstall-saas.sh
      remote_run_script install-saas.sh "$@"
      ensure_forward
      show_credentials
      ;;
    acceptance)
      ensure_forward
      remote_run_script acceptance-saas.sh "$@"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      die "Unknown action: ${action}"
      ;;
  esac
}

main "$@"
