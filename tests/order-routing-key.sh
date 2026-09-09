#!/usr/bin/env bash

# Adds the optional HTTP v2 key only for OrderSvr requests. Test defaults are
# explicit arguments; production GW never derives this value from content.
dc_attach_order_routing_key() {
  local payload="$1" default_location="${2:-}" default_market="${3:-}" default_security="${4:-}"
  python3 - "${payload}" "${default_location}" "${default_market}" "${default_security}" <<'PY'
import json
import sys

request = json.loads(sys.argv[1])
if request.get("serverName") != "OrderSvr" or request.get("key"):
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
    raise SystemExit("OrderSvr test request requires location, marketIndicator and securityID")
request["key"] = "\x1f".join(parts)
print(json.dumps(request, separators=(",", ":")))
PY
}
