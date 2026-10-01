#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${PUBLIC_API_DOCS_TAG:-local/opentradingcore-api-docs:sha-$(git -C "$ROOT" rev-parse --short=12 HEAD)}"
NAME=opentradingcore-api-docs
BACKUP="${NAME}-previous-$(date +%Y%m%d%H%M%S)"

docker image inspect "$IMAGE" >/dev/null
had_previous=false
if docker container inspect "$NAME" >/dev/null 2>&1; then
  docker rename "$NAME" "$BACKUP"
  docker stop "$BACKUP" >/dev/null
  had_previous=true
fi

restore_previous() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  if "$had_previous"; then
    docker rename "$BACKUP" "$NAME"
    docker start "$NAME" >/dev/null
  fi
}

if ! docker run --detach --name "$NAME" --network host --restart unless-stopped "$IMAGE" >/dev/null; then
  restore_previous
  exit 1
fi

for _ in {1..30}; do
  if [[ "$(docker inspect "$NAME" --format '{{.State.Health.Status}}')" == healthy ]] && \
      curl --fail --silent --show-error --max-time 2 http://127.0.0.1:18096/healthz >/dev/null; then
    printf '[public-api-docs] deployed %s\n' "$IMAGE"
    if "$had_previous"; then
      printf '[public-api-docs] previous container preserved as %s\n' "$BACKUP"
    fi
    exit 0
  fi
  sleep 2
done

printf '[public-api-docs] health check failed; restoring previous container\n' >&2
restore_previous
exit 1
