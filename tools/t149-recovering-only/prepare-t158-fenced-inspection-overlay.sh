#!/usr/bin/env bash
# T158: stage opt-in RECOVERING business inspection only in an isolated
# Compose overlay. DOES NOT deploy or change the original T149 config.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: bash prepare-t158-fenced-inspection-overlay.sh <isolated-T149-runtime-root>" >&2
  exit 2
fi
root="$1"
if [[ "$root" != /* ]] || [ "$(basename "$root")" != t149-order-trade-deploy-20261026 ] ||
  [ ! -f "$root/compose.yaml" ]; then
  echo 'T158_DENIED: only the original isolated T149 runtime' >&2;exit 1
fi
stage="$root/t158-fenced-inspection"
mkdir -p "$stage"
compose="$stage/compose.t158.yaml"
printf 'services:\n' > "$compose"
for node in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b; do
  case "$node" in
    ordersvr-*) prefix=order;service=OrderSvr;tag=local/otc-t158-ordersvr:fenced-main-jvm ;;
    tradesvr-*) prefix=trade;service=TradeSvr;tag=local/otc-t158-tradesvr:fenced-main-jvm ;;
  esac
  original="$root/config/$node/application.properties"
  staged="$stage/$node/application.properties"
  mkdir -p "$(dirname "$staged")"
  [ -f "$original" ] || { echo "T158_MISSING_ORIGINAL $node" >&2;exit 1; }
  if grep -Eq "^$prefix.common.nodeRuntime.inspectFencedBusiness=" "$original"; then
    echo "T158_DENIED original config already altered: $node" >&2;exit 1
  fi
  cp "$original" "$staged"
  printf '\n%s.common.nodeRuntime.inspectFencedBusiness=true\n' "$prefix" >> "$staged"
  chmod 600 "$staged"
  printf '  %s:\n    image: %s\n    volumes:\n      - %s:/srv/dc/dc/%s/config/application.properties:ro\n' \
    "$node" "$tag" "$staged" "$service" >> "$compose"
done
# This overlay only replaces five exact services' images and file mounts;
# it never changes ZooKeeper, Gateway, Robot or official Demo containers.
docker compose --project-directory "$root" -f "$root/compose.yaml" \
  -f "$compose" --profile business config --format json |
python3 -c '
import json,sys
data=json.load(sys.stdin)
assert data["name"]=="otc-t149-ha-intake"
base="local/otc-t158-"
for node in ("ordersvr-a","ordersvr-b","ordersvr-c","tradesvr-a","tradesvr-b"):
    service=data["services"][node]
    expected=base+node.split("-")[0]+":fenced-main-jvm"
    assert service["image"]==expected, (node,service["image"])
    assert not service.get("ports"), node
    serviceName="OrderSvr" if node.startswith("ordersvr") else "TradeSvr"
    mounts=[v for v in service["volumes"] if v["target"]=="/srv/dc/dc/"+serviceName+"/config/application.properties"]
    assert len(mounts)==1 and "t158-fenced-inspection" in mounts[0]["source"], (node,mounts)
    assert mounts[0]["read_only"],node
for node in ("zk1","zk2","zk3"):
    assert node in data["services"]
print("T158_FIVE_ISOLATED_ONLY_CONFIG_OVERRIDE_VALIDATED_PASS")
'
echo "T158_STAGED_COMPOSE_OVERLAY=$compose"
echo "T158_NO_DEPLOY_NO_READY original T149 props and official Demo untouched"