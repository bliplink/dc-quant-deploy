#!/usr/bin/env bash
# Post-recreate T153 isolated Common E1 recovery-only regression.
# Auxiliary read-only Java probes in /tmp; never service startup or READY.
set -euo pipefail
if [ "$#" -ne 2 ] || [ ! -d "$1/config" ] || [ ! -d "$2" ] ||
  [ "$(basename "$1")" != "t149-order-trade-deploy-20261026" ]; then
  echo "Usage: bash verify-t153-post-deploy.sh <T149-runtime-root> <Order-target/dependency>" >&2
  exit 2
fi
runtime="$1"
deps="$2"
base="$(cd "$(dirname "$0")" && pwd)"
out="$(mktemp -d /tmp/otc-t153-recreate-check.XXXXXX)"
trap 'rm -rf "$out"' EXIT
javac -source 8 -target 8 -cp "$deps/*" -d "$out" \
  "$base/bootstrap/T149RecoveryOnlyProbe.java" \
  "$base/bootstrap/T150RealEmptyBusinessGenesis.java" \
  "$base/bootstrap/T153RealZkOriginalE1ReadOnlyProbe.java"
for cls in T149RecoveryOnlyProbe T150RealEmptyBusinessGenesis \
    T153RealZkOriginalE1ReadOnlyProbe; do
  javap -verbose -classpath "$out" "$cls" |
    grep 'major version: 52' >/dev/null || {
      echo "T153_FAIL: non Java 8 probe $cls" >&2; exit 1;
    }
done
for node in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b; do
  container="otc-t149-ha-intake-$node-1"
  [ "$(docker inspect --format '{{.State.Running}}' "$container")" = true ] || {
    echo "T153_FAIL: recovering service not running $container" >&2; exit 1;
  }
  for cls in T149RecoveryOnlyProbe T150RealEmptyBusinessGenesis \
      T153RealZkOriginalE1ReadOnlyProbe; do
    docker cp "$out/$cls.class" "$container:/tmp/$cls.class"
  done
done
bash "$base/verify-t150-post-genesis.sh" "$runtime"
bash "$base/verify-t153-live-rf2.sh" "$deps"
echo "T153_POST_RECREATE_6_SIGNED_GENESIS_5_NETTY_DENY_6_LIVE_ZK_ALL_PASS"
echo "T153_NO_READY: historical zero-WAL receipts and actual business install missing"