#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
fakecurl="$tmpdir/curl"
cat > "$fakecurl" <<'SH'
#!/usr/bin/env bash
url="${!#}"
case "${FAKE_CURL_MODE:-}" in
  live-ok)
    [[ "$url" == https://fapi.binance.com/* ]] && printf 200 || printf 000
    ;;
  live-fail-testnet-ok)
    [[ "$url" == https://testnet.binancefuture.com/* ]] && printf 200 || printf 000
    ;;
  all-fail)
    printf 000
    ;;
  *) printf 000 ;;
esac
SH
chmod +x "$fakecurl"

make_env() {
  cat > "$1" <<'ENV'
MYSQL_PASSWORD=keep-secret
APSSVR_BINANCE_REST_URL=https://fapi.binance.com
APSSVR_BINANCE_WS_URL=wss://fstream.binance.com/ws
ENV
}

env1="$tmpdir/live.env"; make_env "$env1"
FAKE_CURL_MODE=live-ok MACOS_BINANCE_CURL_BIN="$fakecurl" \
  "$ROOT/scripts/configure-macos-binance-feed.sh" "$env1" >/dev/null
grep -Fxq 'APSSVR_BINANCE_REST_URL=https://fapi.binance.com' "$env1"
grep -Fxq 'APSSVR_BINANCE_WS_URL=wss://fstream.binance.com/ws' "$env1"
grep -Fxq 'MYSQL_PASSWORD=keep-secret' "$env1"

env2="$tmpdir/testnet.env"; make_env "$env2"
FAKE_CURL_MODE=live-fail-testnet-ok MACOS_BINANCE_CURL_BIN="$fakecurl" \
  "$ROOT/scripts/configure-macos-binance-feed.sh" "$env2" >/dev/null
grep -Fxq 'APSSVR_BINANCE_REST_URL=https://testnet.binancefuture.com' "$env2"
grep -Fxq 'APSSVR_BINANCE_WS_URL=wss://stream.binancefuture.com/ws' "$env2"
grep -Fxq 'MYSQL_PASSWORD=keep-secret' "$env2"

env3="$tmpdir/custom.env"
cat > "$env3" <<'ENV'
APSSVR_BINANCE_REST_URL=https://example.invalid
APSSVR_BINANCE_WS_URL=wss://example.invalid/ws
ENV
FAKE_CURL_MODE=all-fail MACOS_BINANCE_CURL_BIN="$fakecurl" \
  "$ROOT/scripts/configure-macos-binance-feed.sh" "$env3" >/dev/null
grep -Fxq 'APSSVR_BINANCE_REST_URL=https://example.invalid' "$env3"
grep -Fxq 'APSSVR_BINANCE_WS_URL=wss://example.invalid/ws' "$env3"

echo '[macos-binance-feed] PASS: auto live/testnet selection is safe and preserves explicit custom endpoints'
