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
  ./mac-colima-saas.sh fresh [verified build directory]
  ./mac-colima-saas.sh fresh-verified CANDIDATE_DIRECTORY PHYSICAL_RESULT_DIRECTORY
  ./mac-colima-saas.sh verify-common COMMON_REVISION
  ./mac-colima-saas.sh verify-fresh RUN_DIRECTORY
  ./mac-colima-saas.sh verify-order-cancel RUN_DIRECTORY
  ./mac-colima-saas.sh verify-execution RUN_DIRECTORY --transport tcp --rate RATE --seconds SECONDS
  ./mac-colima-saas.sh verify-distributed-execution RUN_DIRECTORY --streams 4 --rate-per-stream RATE --seconds 60
  ./mac-colima-saas.sh verify-async-recovery RUN_DIRECTORY
  ./mac-colima-saas.sh verify-ha RUN_DIRECTORY {term,kill} [FIRST_ORDER_SLOT [FIRST_ORDER_ROBOT_LOCATION]]
  ./mac-colima-saas.sh roll-voter RUN_DIRECTORY {order,trade} {A,B} [--fault term|kill] [--signed-business|--order-only-business] [--robot-traffic]
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
      # T547: check live Order/Trade BEFORE uninstall. deploy-saas.sh runs
      # after uninstall and would otherwise discover zero live peers too late.
      remote_shell "cd $(printf '%q' "${REMOTE_REPO}") && sudo -E python3 ./tests/check_certified_live_upgrade_preflight.py --order-enabled true --trade-enabled true"
      remote_run_script uninstall-saas.sh
      remote_run_script install-saas.sh "$@"
      ensure_forward
      show_credentials
      ;;
    fresh|fresh-verified)
      local stamp build_dir run_dir build_seconds active_generation order_base trade_base md_base
      SECONDS=0
      stamp="$(date +%Y%m%d-%H%M%S)"
      run_dir="${HOME}/.opentradingcore/mac-demo-${stamp}"
      if [[ "$action" == fresh-verified ]]; then
        [[ "$#" -eq 2 && "$1" == /* && "$2" == /* && -f "$1/commit.sha" && -f "$1/jar.sha" ]] ||
          die "Usage: ./mac-colima-saas.sh fresh-verified CANDIDATE_DIRECTORY PHYSICAL_RESULT_DIRECTORY"
        build_dir="${HOME}/.opentradingcore/mac-demo-build-${stamp}"
        order_base="${MAC_DEMO_ORDER_BASE:-}"
        trade_base="${MAC_DEMO_TRADE_BASE:-}"
        md_base="${MAC_DEMO_MD_BASE:-$(docker inspect -f '{{.Image}}' dc-saas-mdsvr)}"
        active_generation="$(docker inspect -f '{{if .State.Running}}{{index .Config.Labels "com.docker.compose.project"}}{{end}}' dc-saas-gateway 2>/dev/null || true)"
        if [[ "$active_generation" =~ ^mac-demo-[0-9]{8}-[0-9]{6}$ ]]; then
          # The builder reuses dependencies only after comparing the complete library list and bytes.
          order_base="${order_base:-$(docker inspect -f '{{.Image}}' "${active_generation}-order-a-hostready" 2>/dev/null || true)}"
          trade_base="${trade_base:-$(docker inspect -f '{{.Image}}' "${active_generation}-trade-a-hostready" 2>/dev/null || true)}"
        fi
        MAC_DEMO_ORDER_BASE="$order_base" MAC_DEMO_TRADE_BASE="$trade_base" MAC_DEMO_MD_BASE="$md_base" \
          MAC_DEMO_MD_SOURCE="${MAC_DEMO_MD_SOURCE:-${SCRIPT_DIR}/.work/t446-md-price-independent}" \
        MAC_DEMO_COMMON_REVISION="$(cat "$1/commit.sha")" \
          MAC_DEMO_VERIFIED_COMMON_DIR="$1" MAC_DEMO_VERIFIED_COMMON_SHA256="$(cat "$1/jar.sha")" \
          MAC_DEMO_VERIFIED_COMMON_RESULT="$2" MAC_DEMO_REQUIRE_INTERRUPTED_RETURN=true \
          MAC_DEMO_PROJECTION_HISTORY_SOURCE="${MAC_DEMO_PROJECTION_HISTORY_SOURCE:-${SCRIPT_DIR}/.work/projectionsvr}" \
          bash "${SCRIPT_DIR}/scripts/build-mac-demo-core.sh" "${build_dir}"
      else
        [[ "$#" -le 1 ]] || die "Usage: ./mac-colima-saas.sh fresh [verified build directory]"
        build_dir="${1:-${HOME}/.opentradingcore/mac-demo-build-${stamp}}"
        if [[ "$#" == 0 ]]; then
          bash "${SCRIPT_DIR}/scripts/build-mac-demo-core.sh" "${build_dir}"
        fi
      fi
      build_seconds="$SECONDS"
      log "Build/prepared images: ${build_seconds}s. New generation: ${run_dir}"
      python3 "${SCRIPT_DIR}/scripts/mac-demo-fresh.py" "${run_dir}" "${build_dir}" --apply --verify-business
      log "Fresh startup, physical and business checks: $((SECONDS - build_seconds))s."
      ;;
    verify-common)
      [[ "$#" == 1 ]] || die "Usage: ./mac-colima-saas.sh verify-common COMMON_REVISION"
      local common_stamp candidate_dir common_result_dir
      common_stamp="$(date +%Y%m%d-%H%M%S)"
      candidate_dir="${HOME}/.opentradingcore/t554-common-candidates/${common_stamp}"
      common_result_dir="${HOME}/.opentradingcore/t554-common-verifications/${common_stamp}"
      log "Common fault verification: ${common_result_dir}"
      MAC_DEMO_REQUIRE_INTERRUPTED_RETURN="${MAC_DEMO_REQUIRE_INTERRUPTED_RETURN:-true}" \
        bash "${SCRIPT_DIR}/scripts/build-mac-common-candidate.sh" "$1" "$candidate_dir" "$common_result_dir"
      ;;
    verify-fresh)
      [[ "$#" == 1 ]] || die "Usage: ./mac-colima-saas.sh verify-fresh RUN_DIRECTORY"
      bash "${SCRIPT_DIR}/scripts/verify-mac-demo-fresh.sh" "$1"
      ;;
    verify-matching)
      [[ "$#" == 1 ]] || die "Usage: ./mac-colima-saas.sh verify-matching RUN_DIRECTORY"
      python3 "${SCRIPT_DIR}/scripts/verify-mac-demo-multi-maker.py" "$1"
      ;;
    verify-order-cancel)
      [[ "$#" == 1 ]] || die "Usage: ./mac-colima-saas.sh verify-order-cancel RUN_DIRECTORY"
      python3 "${SCRIPT_DIR}/scripts/verify-mac-demo-order-cancel-capacity.py" "$1"
      ;;
    verify-execution)
      [[ "$#" -ge 1 ]] || die "Usage: ./mac-colima-saas.sh verify-execution RUN_DIRECTORY --transport tcp --rate RATE --seconds SECONDS"
      python3 "${SCRIPT_DIR}/scripts/verify-mac-demo-execution-capacity.py" "$@"
      ;;
    verify-distributed-execution)
      [[ "$#" -ge 1 ]] || die "Usage: ./mac-colima-saas.sh verify-distributed-execution RUN_DIRECTORY --streams 4 --rate-per-stream RATE --seconds 60"
      python3 "${SCRIPT_DIR}/scripts/verify-mac-demo-distributed-execution-capacity.py" "$@"
      ;;
    verify-async-recovery)
      [[ "$#" -eq 1 ]] || die "Usage: ./mac-colima-saas.sh verify-async-recovery RUN_DIRECTORY"
      python3 "${SCRIPT_DIR}/scripts/verify-mac-demo-async-rpo.py" "$1"
      python3 "${SCRIPT_DIR}/scripts/verify-mac-demo-async-reservation-loss.py" "$1"
      ;;
    verify-ha)
      [[ "$#" -ge 2 && "$#" -le 4 && "$2" =~ ^(term|kill)$ && "${3:-A}" =~ ^[AB]$ ]] ||
        die "Usage: ./mac-colima-saas.sh verify-ha RUN_DIRECTORY {term,kill} [FIRST_ORDER_SLOT [FIRST_ORDER_ROBOT_LOCATION]]"
      local order_first="${3:-A}" order_second=B slot
      if [[ "$order_first" == B ]]; then order_second=A; fi
      local roll=(python3 "${SCRIPT_DIR}/scripts/roll-mac-demo-voter.py" "$1")
      local checks=(--fault "$2" --robot-traffic --timeout 3600)
      local first_order=(order "$order_first" "${checks[@]}" --order-only-business)
      if [[ "$#" -eq 4 ]]; then first_order+=(--robot-location "$4"); fi
      "${roll[@]}" "${first_order[@]}"
      "${roll[@]}" order "$order_second" "${checks[@]}" --signed-business
      for slot in A B; do
        "${roll[@]}" trade "$slot" "${checks[@]}" --signed-business
      done
      ;;
    roll-voter)
      python3 "${SCRIPT_DIR}/scripts/roll-mac-demo-voter.py" "$@"
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
