#!/usr/bin/env bash
# T153 live E1 initial-genesis observation ONLY. No ZK writes/CAS, WAL
# admission, service restart, READY, external ports or Docker image changes.
set -euo pipefail
if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
  echo "Usage: bash verify-t153-live-rf2.sh <existing Order target/dependency directory>" >&2
  exit 2
fi
base="$(cd "$(dirname "$0")" && pwd)"
out="$(mktemp -d /tmp/otc-t153-readonly.XXXXXX)"
trap 'rm -rf "$out"' EXIT
javac -source 8 -target 8 -cp "$1/*" -d "$out" \
  "$base/bootstrap/T153RealZkOriginalE1ReadOnlyProbe.java"
if ! javap -verbose -classpath "$out" T153RealZkOriginalE1ReadOnlyProbe |
    grep 'major version: 52' >/dev/null; then
  echo "T153_FAIL: read-only probe must be Java 8 compatible" >&2
  exit 1
fi
# Candidate names and placements are fixed by original T149 signed manifest.
cases=(
  'ordersvr-a OrderSvr P090 OrderSvrA OrderSvrB OrderSvrA'
  'ordersvr-b OrderSvr P090 OrderSvrA OrderSvrB OrderSvrB'
  'ordersvr-b OrderSvr P091 OrderSvrC OrderSvrB OrderSvrB'
  'ordersvr-c OrderSvr P091 OrderSvrC OrderSvrB OrderSvrC'
  'tradesvr-a TradeSvr P090 TradeSvrA TradeSvrB TradeSvrA'
  'tradesvr-b TradeSvr P090 TradeSvrA TradeSvrB TradeSvrB'
)
staged='|'
passed=0
for spec in "${cases[@]}"; do
  read -r id service partition primary replica local <<< "$spec"
  node="otc-t149-ha-intake-${id}-1"
  case "$staged" in *"|$id|"*) already=yes ;; *) already=no ;; esac
  if [ "$already" = no ]; then
    if ! docker inspect --format '{{.State.Running}}' "$node" | grep -qx true; then
      echo "T153_FAIL: isolated original voter not running: $node" >&2
      exit 1
    fi
    docker cp "$out/T153RealZkOriginalE1ReadOnlyProbe.class" \
      "$node:/tmp/T153RealZkOriginalE1ReadOnlyProbe.class"
    staged="${staged}${id}|"
    # A recover-only candidate contains only existing original Genesis
    # files. This is a CURRENT disk inventory, not historical 0-ACK proof.
    disk="$(docker exec "$node" sh -c 'find /srv/dc/data -type f' |
      sed 's#^/srv/dc/data/##')"
    if [ -z "$disk" ]; then
      echo "T153_FAIL: missing original Genesis files on $node" >&2
      exit 1
    fi
    unexpected="$(printf '%s\n' "$disk" |
      grep -Ev '^t150-original-genesis/P(090|091)/(receipts/[A-Za-z0-9]+\.rsa2048|sealed/genesis-e1\.(quorum|snapshot)|node-voter/original-e1-[A-Za-z0-9]+\.genesis)$' || true)"
    if [ -n "$unexpected" ]; then
      echo "T153_FAIL: unexpected non-Genesis durable source on $node" >&2
      exit 1
    fi
    echo "T153_CURRENT_NODE_DISK_ONLY_ORIGINAL_GENESIS_PASS $node"
  fi
  response="$(docker exec "$node" sh -c \
    "cd /srv/dc/dc/$service && java -cp '/tmp:classes:config:lib/*' \
      T153RealZkOriginalE1ReadOnlyProbe '$service' '$partition' '$primary' '$replica' '$local'")"
  echo "$response" | grep '^T153_READONLY_REAL_ZK_RF2_ORIGINAL_RSA_GENESIS_PASS '
  passed=$((passed+1))
done
if [ "$passed" -ne 6 ]; then echo "T153_FAIL: missing original member" >&2;exit 1;fi
echo "T153_LIVE_ZK_BOTH_LEASES_ORIGINAL_RSA_READONLY_6_OF_6_PASS"
echo "T153_NO_GO: current clean disks are not proof of historical zero ACK;"
echo "T153_NO_GO: one Mac is not two physical hosts; business state/install/READY are not wired"