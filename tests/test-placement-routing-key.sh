#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=order-routing-key.sh
. "${SCRIPT_DIR}/order-routing-key.sh"
PYTHON_BIN="${PYTHON_BIN:-python3}"

assert_key() {
  local server="$1" expected="$2" payload actual
  payload="{\"serverName\":\"${server}\",\"method\":\"probe\",\"content\":{\"Location\":\"WEB_E2E\",\"MarketIndicator\":\"4\",\"SecurityID\":\"BTCUSDT\"}}"
  actual="$(dc_attach_placement_key "${payload}" WEB_E2E 4 BTCUSDT | "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin).get("key", ""))')"
  [[ "${actual}" == "${expected}" ]]
}

separator=$'\x1f'
assert_key OrderSvr "WEB_E2E${separator}4${separator}BTCUSDT"
assert_key MDSvr "WEB_E2E${separator}4${separator}BTCUSDT"
assert_key TradeSvr "WEB_E2E"

existing='{"serverName":"MDSvr","key":"operator-selected","content":{}}'
actual="$(dc_attach_placement_key "${existing}" WEB_E2E 4 BTCUSDT | "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin)["key"])')"
[[ "${actual}" == "operator-selected" ]]

legacy="$(dc_attach_order_routing_key '{"serverName":"MDSvr","content":{}}' WEB_E2E 4 BTCUSDT | "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin)["key"])')"
[[ "${legacy}" == "WEB_E2E${separator}4${separator}BTCUSDT" ]]

echo "placement routing key tests passed"
