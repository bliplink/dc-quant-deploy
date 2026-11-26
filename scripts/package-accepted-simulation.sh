#!/usr/bin/env bash
# Export the tested OCI files for delivery without distributing the owner's decryption identity.
set -euo pipefail
umask 077
run_id="${1:?expected a successful acceptance run ID}"
identity="${2:?expected the owner identity file}"
destination="${3:?expected a new private release directory}"
[[ "$run_id" =~ ^[0-9]+$ && -f "$identity" && ! -e "$destination" ]]
root="$(cd "$(dirname "$0")/.." && pwd)"
repository=bliplink/dc-quant-deploy
revision="$(git -C "$root" rev-parse HEAD)"
verified="$(gh run view "$run_id" --repo "$repository" --json conclusion,headSha,headBranch,workflowName,jobs --jq '
  select(.conclusion=="success" and .headBranch=="release/public-simulation-20261126" and
         .workflowName=="Public simulation candidate images" and
         any(.jobs[]; .name=="Clean Linux installation" and .conclusion=="success") and
         any(.jobs[]; .name=="Clean Linux ARM64 installation" and .conclusion=="success")) | .headSha')"
[[ "$revision" == "$verified" ]] || { echo "Use the exact checkout for the accepted Linux run" >&2; exit 1; }
mkdir -p "$(dirname "$destination")"
mkdir -m 700 "$destination"
work="$(mktemp -d "$destination/.export-XXXXXXXX")"
trap 'rm -rf "$work"' EXIT
gh run download "$run_id" --repo "$repository" --name "accepted-linux-amd64-images-$revision" --dir "$work/accepted"
gh run download "$run_id" --repo "$repository" --name "accepted-linux-arm64-images-$revision" --dir "$work/accepted-arm"
cmp "$work/accepted/simulation-images.json" "$work/accepted-arm/simulation-images.json"
for group in public-web trade-web tenant-web platform-web api-docs trading-core robot admin-bootstrap login manager liquidation price-feed projection; do
  gh run download "$run_id" --repo "$repository" --name "candidate-$group-$revision" --dir "$work/artifact"
  components=("$group")
  if [[ "$group" == trading-core ]]; then components=(order trade market-data gateway); fi
  for service in "${components[@]}"; do
    pin="$(git -C "$root" rev-parse "HEAD:sources/$service")"
    name="$service-$pin.oci.tar"
    age --decrypt --identity "$identity" --output "$work/$name" "$work/artifact/$name.age"
    expected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["images"][sys.argv[2]])' \
        "$work/accepted/simulation-images.json" "$service")"
    actual="$(shasum -a 256 "$work/$name" | cut -d' ' -f1)"
    [[ "$actual" == "$expected" ]]
    python3 "$root/scripts/verify-simulation-oci.py" "$work/$name" "$pin"
    mv "$work/$name" "$destination/"
  done
  rm -r "$work/artifact"
done
# This manifest is the completion marker. A partial export has no installable manifest.
mv "$work/accepted/simulation-images.json" "$destination/"
shasum -a 256 "$destination/simulation-images.json"
