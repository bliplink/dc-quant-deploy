#!/usr/bin/env bash
# Stage the exact tracked deployment tree next to the release's verified OCI files.
set -euo pipefail
bundle="${1:?expected release directory}"
root="$(cd "$(dirname "$0")/.." && pwd)"
revision="$(git -C "$root" rev-parse HEAD)"
mkdir "$bundle/deployment"
git -C "$bundle/deployment" init --quiet
git -C "$bundle/deployment" fetch --quiet --depth=1 --no-tags "$root" "$revision"
git -C "$bundle/deployment" checkout --quiet --detach FETCH_HEAD
install -m 755 "$bundle/deployment/scripts/install-simulation-bundle.sh" "$bundle/install.sh"
