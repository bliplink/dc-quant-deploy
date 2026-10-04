#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${ROOT}/.env.prod}"
PROFILE="${MACOS_BINANCE_FEED_PROFILE:-auto}"
CURL_BIN="${MACOS_BINANCE_CURL_BIN:-curl}"
LIVE_REST="${MACOS_BINANCE_LIVE_REST_URL:-https://fapi.binance.com}"
LIVE_WS="${MACOS_BINANCE_LIVE_WS_URL:-wss://fstream.binance.com/ws}"
TESTNET_REST="${MACOS_BINANCE_TESTNET_REST_URL:-https://testnet.binancefuture.com}"
TESTNET_WS="${MACOS_BINANCE_TESTNET_WS_URL:-wss://stream.binancefuture.com/ws}"

[[ -f "$ENV_FILE" ]] || { echo "[saas-macos] ERROR: env file not found: $ENV_FILE" >&2; exit 1; }
command -v "$CURL_BIN" >/dev/null 2>&1 || { echo "[saas-macos] ERROR: curl is required for Binance feed preflight." >&2; exit 1; }

get_env() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

set_feed() {
  local rest="$1" ws="$2" label="$3"
  "${SCRIPT_DIR}/upsert-env-value.sh" "$ENV_FILE" APSSVR_BINANCE_REST_URL "$rest"
  "${SCRIPT_DIR}/upsert-env-value.sh" "$ENV_FILE" APSSVR_BINANCE_WS_URL "$ws"
  echo "[saas-macos] Binance Futures market feed: ${label} (${rest}, ${ws})"
}

probe_rest() {
  local base="${1%/}"
  local code
  code="$($CURL_BIN -sS -o /dev/null -w '%{http_code}' --max-time "${MACOS_BINANCE_PROBE_TIMEOUT_SECONDS:-6}" "${base}/fapi/v1/ping" 2>/dev/null || true)"
  [[ "$code" == "200" ]]
}

case "$PROFILE" in
  live)
    probe_rest "$LIVE_REST" || { echo "[saas-macos] ERROR: Binance Futures live endpoint is not reachable from this host." >&2; exit 1; }
    set_feed "$LIVE_REST" "$LIVE_WS" live
    ;;
  testnet)
    probe_rest "$TESTNET_REST" || { echo "[saas-macos] ERROR: Binance Futures testnet endpoint is not reachable from this host." >&2; exit 1; }
    set_feed "$TESTNET_REST" "$TESTNET_WS" testnet
    ;;
  auto)
    current_rest="$(get_env APSSVR_BINANCE_REST_URL)"
    current_ws="$(get_env APSSVR_BINANCE_WS_URL)"
    # Respect an explicitly customized endpoint. Auto-selection is only for the
    # stock live defaults copied from .env.example.
    if [[ -n "$current_rest" && "$current_rest" != "$LIVE_REST" ]]; then
      echo "[saas-macos] Binance Futures market feed: preserving custom endpoint ${current_rest}."
      exit 0
    fi
    if [[ -n "$current_ws" && "$current_ws" != "$LIVE_WS" ]]; then
      echo "[saas-macos] Binance Futures market feed: preserving custom WebSocket endpoint ${current_ws}."
      exit 0
    fi
    if probe_rest "$LIVE_REST"; then
      set_feed "$LIVE_REST" "$LIVE_WS" live
    elif probe_rest "$TESTNET_REST"; then
      echo "[saas-macos] Binance Futures live endpoint is unavailable from this host; falling back to testnet for local validation."
      set_feed "$TESTNET_REST" "$TESTNET_WS" testnet
    else
      echo "[saas-macos] ERROR: neither Binance Futures live nor testnet REST endpoint is reachable." >&2
      exit 1
    fi
    ;;
  *)
    echo "[saas-macos] ERROR: MACOS_BINANCE_FEED_PROFILE must be auto, live, or testnet." >&2
    exit 2
    ;;
esac
