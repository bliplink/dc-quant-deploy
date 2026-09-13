#!/usr/bin/env bash

# Adds the HTTP placement key for instrument-routed OrderSvr/MDSvr requests
# and the location-only key for TradeSvr requests. Test defaults are explicit
# arguments; production GW never derives these values from content.
dc_attach_placement_key() {
  local payload="$1" default_location="${2:-}" default_market="${3:-}" default_security="${4:-}"
  local python_bin="${PYTHON_BIN:-python3}"
  "${python_bin}" - "${payload}" "${default_location}" "${default_market}" "${default_security}" <<'PY'
import json
import sys

request = json.loads(sys.argv[1])
server_name = request.get("serverName")
if server_name not in ("OrderSvr", "MDSvr", "TradeSvr") or request.get("key"):
    print(json.dumps(request, separators=(",", ":")))
    raise SystemExit(0)

content = request.get("content") or {}
def value(*names, default=""):
    for name in names:
        current = content.get(name)
        if current is not None and str(current).strip():
            return str(current).strip()
    return default.strip()

location = value("Location", "location", default=sys.argv[2])
if server_name == "TradeSvr":
    if not location:
        raise SystemExit("TradeSvr test request requires location")
    request["key"] = location
    print(json.dumps(request, separators=(",", ":")))
    raise SystemExit(0)

parts = (
    location,
    value("MarketIndicator", "marketIndicator", default=sys.argv[3]),
    value("SecurityID", "securityID", "securityId", "securityid", default=sys.argv[4]),
)
if not all(parts):
    raise SystemExit(
        f'{server_name} test request requires '
        'location, marketIndicator and securityID'
    )
request["key"] = "\x1f".join(parts)
print(json.dumps(request, separators=(",", ":")))
PY
}

# Backward-compatible name used by the existing host acceptance scripts.
dc_attach_order_routing_key() {
  dc_attach_placement_key "$@"
}
