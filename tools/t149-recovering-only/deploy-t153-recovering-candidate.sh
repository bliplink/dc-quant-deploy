#!/usr/bin/env bash
# T153 local-only deployment. Recreates five RECOVERING candidate services
# in the exact T149 project; leaves three ZK and T84/official containers alone.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: bash deploy-t153-recovering-candidate.sh <existing-absolute-T149-runtime-path>" >&2
  exit 2
fi
runtime="$1"
if [[ "$runtime" != /* ]] || [ ! -d "$runtime" ] || [ "$runtime" != "${runtime%/}" ] ||
     [ "$(basename "$runtime")" != "t149-order-trade-deploy-20261026" ] ||
     [ ! -f "$runtime/.env" ] || [ ! -f "$runtime/compose.yaml" ]; then
  echo "T153_DENIED: explicit existing isolated T149 runtime required" >&2
  exit 1
fi
base="$(cd "$(dirname "$0")" && pwd)"
expected="58c71dd41b70cbb4ac97d6ab3887978c5204e2d4a464017257a23908b961f659"
for image in ordersvr tradesvr; do
  tag="local/otc-t153-$image:common-e1-candidate"
  arch="$(docker image inspect "$tag" --format '{{.Architecture}}')"
  if [ "$arch" != arm64 ]; then
    echo "T153_DENIED: not an ARM64 candidate: $tag" >&2
    exit 1
  fi
  case "$image" in ordersvr) service=OrderSvr ;; tradesvr) service=TradeSvr ;; esac
  docker run --rm --network none --read-only --entrypoint sh "$tag" -c '
    set -eu
    dir="/srv/dc/dc/$1/lib"
    expected="$2"
    set -- "$dir"/com.app.common-*.jar
    [ "$#" -eq 1 ] && [ -f "$1" ] || exit 13
    actual=$(sha256sum "$1" | cut -d " " -f1)
    [ "$actual" = "$expected" ]
  ' sh "$service" "$expected"
  echo "T153_PINNED_SINGLE_COMMON_ARM64_OK $tag"
done
zkBefore=""
for n in zk1 zk2 zk3; do
  id="$(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.Id}}')"
  zkBefore="$zkBefore $id"
done
# Explicitly update ONLY the five business names. --no-deps means ZK never
# restarts. Old T149 Genesis/certificate volumes remain unchanged.
docker compose --project-directory "$runtime" -f "$runtime/compose.yaml" \
  -f "$base/compose.t153-candidate.yaml" --profile business up -d \
  --no-deps --force-recreate ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b
# Compose "Started" only means Docker launched PID 1. The original RECOVERING
# JVM deliberately rejects an old ZK ephemeral owner until its session timeout.
# Do not bypass this fence, mutate ZK leases, or declare success prematurely.
sleep 10
restart_nodes=""
for node in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b; do
  c="otc-t149-ha-intake-$node-1"
  if [ "$(docker inspect "$c" --format '{{.State.Running}}')" != true ]; then
    # Consume ALL log output with pipefail: grep -q exits early and makes
    # docker logs receive SIGPIPE, falsely reporting an unexpected JVM error.
    if ! docker logs --tail 90 "$c" 2>&1 |
        grep -F 'recovering node lease owned by another ZK session' >/dev/null; then
      echo "T153_FAIL: unexpected RECOVERING JVM exit: $c" >&2
      exit 1
    fi
    restart_nodes="$restart_nodes $node"
  fi
done
if [ -n "$restart_nodes" ]; then
  echo "T153_CORRECT_OLD_ZK_SESSION_FENCE: waiting for old lease retirement"
  sleep 12
  # One retry AFTER original ZK ephemeral session expiry; no forced deletion.
  # shellcheck disable=SC2086
  docker compose --project-directory "$runtime" -f "$runtime/compose.yaml" \
    -f "$base/compose.t153-candidate.yaml" --profile business start $restart_nodes
fi
# At least one full 8s ZK timeout window of actual JVM stability is required.
sleep 12
zkAfter=""
for n in zk1 zk2 zk3; do
  id="$(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.Id}}')"
  zkAfter="$zkAfter $id"
done
if [ "$zkBefore" != "$zkAfter" ]; then
  echo "T153_FAIL: unexpected isolated ZK replacement" >&2
  exit 1
fi
for node in ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b; do
  c="otc-t149-ha-intake-$node-1"
  running="$(docker inspect "$c" --format '{{.State.Running}}')"
  source="$(docker inspect "$c" --format '{{.Config.Image}}')"
  expectedTag="local/otc-t153-${node%%-*}:common-e1-candidate"
  bindings="$(docker inspect "$c" --format '{{json .HostConfig.PortBindings}}')"
  if [ "$running" != true ] || [ "$source" != "$expectedTag" ] ||
       { [ "$bindings" != null ] && [ "$bindings" != "{}" ]; }; then
    echo "T153_FAIL: candidate unhealthy, wrong image or published external port $c" >&2
    exit 1
  fi
  echo "T153_ISOLATED_NEW_ARM64_RECOVERING_PROCESS_RUNNING $c"
done
echo "T153_FIVE_CANDIDATES_UP_THREE_ORIGINAL_ZK_UNCHANGED_PASS"
echo "T153_NO_READY: deployment alone is not certified business install or historical WAL audit"