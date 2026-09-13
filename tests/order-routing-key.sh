#!/usr/bin/env bash

# Adds the HTTP placement key for services routed by
# location + marketIndicator + securityID. Test defaults are explicit
# arguments; production GW never derives this value from content.
dc_attach_placement_key() {
  local payload="$1" default_location="${2:-}" default_market="${3:-}" default_security="${4:-}"
  local python_bin="${PYTHON_BIN:-python3}"
  "${python_bin}" - "${payload}" "${default_location}" "${default_market}" "${default_security}" <<'PY'
import json
import sys

request = json.loads(sys.argv[1])
if request.get("serverName") not in ("OrderSvr", "MDSvr") or request.get("key"):
    print(json.dumps(request, separators=(",", ":")))
    raise SystemExit(0)

content = request.get("content") or {}
def value(*names, default=""):
    for name in names:
        current = content.get(name)
        if current is not None and str(current).strip():
            return str(current).strip()
    return default.strip()

parts = (
    value("Location", "location", default=sys.argv[2]),
    value("MarketIndicator", "marketIndicator", default=sys.argv[3]),
    value("SecurityID", "securityID", "securityId", "securityid", default=sys.argv[4]),
)
if not all(parts):
    raise SystemExit(
        f'{request.get("serverName")} test request requires '
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
