#!/usr/bin/env bash
# Build OCI archives from the exact source commits pinned in this release.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:?usage: build-public-simulation-web.sh OUTPUT_DIRECTORY [trade-web|public-web|api-docs|tenant-web|platform-web ...]}"
shift
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"
if [[ $# == 0 ]]; then set -- trade-web public-web api-docs tenant-web platform-web; fi
for service in "$@"; do
  case "$service" in trade-web|public-web|api-docs|tenant-web|platform-web) ;; *) echo "Unknown web component: $service" >&2; exit 2 ;; esac
  pin="$(git -C "$root" rev-parse "HEAD:sources/$service")"
  src="$root/sources/$service"
  [[ "$(git -C "$src" rev-parse --verify "$pin^{commit}")" == "$pin" ]]
  # git archive keeps developer settings and untracked build outputs out of COPY .
  (
    work="$(mktemp -d "$dest/.build-$service-XXXXXXXX")"
    trap 'rm -rf "$work"' EXIT
    mkdir "$work/source"
    git -C "$src" archive "$pin" | tar -x -C "$work/source"
    context="$work/source"
    file="$context/Dockerfile"
    extra=()
    if [[ "$service" == public-web ]]; then
      context="$work/context"
      mkdir -p "$context/site"
      cp -R "$work/source/assets" "$work/source/index.html" "$work/source/robots.txt" "$work/source/sitemap.xml" "$context/site/"
      cp "$root/config/frontend-proxies/public-web.conf.template" "$context/default.conf.template"
      file="$root/docker/public-simulation-site.Dockerfile"
      if [[ -n "${SIMULATION_NGINX_LAYOUT:-}" ]]; then
        extra=(--build-context "webbase=oci-layout://${SIMULATION_NGINX_LAYOUT}:base" --build-arg NGINX_IMAGE=webbase)
      fi
    elif [[ "$service" == api-docs ]]; then
      context="$work/context"
      bash "$work/source/scripts/prepare-public-api-docs-context.sh" "$context"
      file="$work/source/docs/public-api/Dockerfile"
    fi
    docker buildx build --platform linux/amd64,linux/arm64 \
      --label "org.opencontainers.image.revision=$pin" \
      --tag "otc-simulation/$service:$pin" \
      ${extra[@]+"${extra[@]}"} --output "type=oci,dest=$work/image.tar" -f "$file" "$context"
    python3 "$root/scripts/verify-simulation-oci.py" "$work/image.tar" "$pin"
    mv "$work/image.tar" "$dest/$service-$pin.oci.tar"
  )
done
