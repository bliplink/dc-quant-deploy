#!/usr/bin/env bash
# Host-network Docker containers can have an empty /etc/resolv.conf under
# Colima even though macOS itself resolves domains. Fail before starting
# outbound market-data WebSocket subscriptions.
set -euo pipefail
if (($# == 0)); then
  echo "Usage: $0 RUNNING_HOST_NETWORK_CONTAINER [...]" >&2
  exit 2
fi

failures=0
for container in "$@"; do
  state="$(docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null || true)"
  mode="$(docker inspect "$container" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true)"
  if [[ "$state" != true ]]; then
    echo "HOST_NETWORK_DNS_NOT_RUNNING $container"; failures=$((failures+1)); continue
  fi
  if [[ "$mode" != host ]]; then
    echo "HOST_NETWORK_DNS_NOT_HOST_MODE $container mode=$mode"
    failures=$((failures+1)); continue
  fi
  resolvers="$(docker exec "$container" sh -c 'grep -E "^nameserver[[:space:]]+[^[:space:]]+" /etc/resolv.conf' 2>/dev/null || true)"
  if [[ -z "$resolvers" ]]; then
    echo "HOST_NETWORK_DNS_MISSING $container"
    failures=$((failures+1))
  else
    echo "HOST_NETWORK_DNS_PRESENT $container"
  fi
done
if ((failures)); then
  echo "HOST_NETWORK_DNS_NO_GO failures=$failures" >&2
  exit 1
fi
echo "HOST_NETWORK_DNS_CONFIG_PASS"