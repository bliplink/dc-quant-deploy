#!/usr/bin/env bash
set -euo pipefail
umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf '%s\n' "${SIMULATION_ACCEPTANCE_AGE_KEY:?missing candidate identity}" > "$work/key"
unset SIMULATION_ACCEPTANCE_AGE_KEY
for job in public-web trade-web tenant-web platform-web api-docs trading-core robot admin-bootstrap login manager liquidation price-feed projection; do
  mkdir "$work/artifact"
  gh run download "$GITHUB_RUN_ID" --name "candidate-$job-$GITHUB_SHA" --dir "$work/artifact"
  components=("$job")
  if [[ "$job" == trading-core ]]; then components=(order trade market-data gateway); fi
  for service in "${components[@]}"; do
    pin="$(git rev-parse "$GITHUB_SHA:sources/$service")"
    name="$service-$pin.oci.tar"
    age -d -i "$work/key" -o "$work/$name" "$work/artifact/$name.age"
    expected="$(awk -v name="$name" '$2 == name {print $1}' "$work/artifact/SHA256SUMS")"
    [[ "$expected" =~ ^[a-f0-9]{64}$ ]]
    (cd "$work" && printf '%s  %s\n' "$expected" "$name" | sha256sum -c -)
    python3 scripts/verify-simulation-oci.py "$work/$name" "$pin"
    skopeo copy --quiet "oci-archive:$work/$name" "docker-daemon:otc-simulation/$service:$pin"
    rm "$work/$name" "$work/artifact/$name.age"
  done
  rm -r "$work/artifact"
done
