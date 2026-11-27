#!/usr/bin/env bash
set -euo pipefail
umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf '%s\n' "${SIMULATION_ACCEPTANCE_AGE_KEY:?missing candidate identity}" > "$work/key"
unset SIMULATION_ACCEPTANCE_AGE_KEY
source_run="$GITHUB_RUN_ID"
source_revision="$GITHUB_SHA"
if [[ -n "${CANDIDATE_RUN_ID:-}" ]]; then
  [[ "$CANDIDATE_RUN_ID" =~ ^[0-9]+$ ]]
  source_run="$CANDIDATE_RUN_ID"
  gh run view "$source_run" --json workflowDatabaseId,headBranch,headSha,jobs > "$work/source-run.json"
  workflow_id="$(gh run view "$GITHUB_RUN_ID" --json workflowDatabaseId --jq .workflowDatabaseId)"
  source_revision="$(python3 - "$work/source-run.json" "$workflow_id" <<'PYSOURCE'
import json
import re
import sys
run = json.load(open(sys.argv[1]))
groups = "public-web trade-web tenant-web platform-web api-docs trading-core robot admin-bootstrap login manager liquidation price-feed projection".split()
success = {job["name"] for job in run["jobs"] if job["conclusion"] == "success"}
if (str(run["workflowDatabaseId"]) != sys.argv[2] or run["headBranch"] != "release/public-simulation-20261126"
        or not re.fullmatch("[a-f0-9]{40}", run["headSha"])
        or not all("Candidate " + name in success for name in groups)):
    raise SystemExit("Expected every candidate build to pass in the release repository")
print(run["headSha"])
PYSOURCE
)"
  git fetch --quiet --depth=1 origin "$source_revision"
  git diff --quiet "$source_revision" "$GITHUB_SHA" -- sources .gitmodules config/public-simulation-service-pins.tsv \
    config/public-simulation-maven-settings.xml config/gateway-publicMethodWhitelist.csv scripts/java scripts/build-public-simulation-\* \
    scripts/build-mac-demo-notification-fanout.py scripts/verify-mac-common-failover.sh scripts/finalize-mac-common-failover.py
  echo "Installer diagnostic at $GITHUB_SHA using verified candidate artifacts from $source_revision" >> "$GITHUB_STEP_SUMMARY"
fi
for job in public-web trade-web tenant-web platform-web api-docs trading-core robot admin-bootstrap login manager liquidation price-feed projection; do
  mkdir "$work/artifact"
  gh run download "$source_run" --name "candidate-$job-$source_revision" --dir "$work/artifact"
  components=("$job")
  if [[ "$job" == trading-core ]]; then components=(order trade market-data gateway); fi
  for service in "${components[@]}"; do
    pin="$(git rev-parse "$GITHUB_SHA:sources/$service")"
    name="$service-$pin.oci.tar"
    age -d -i "$work/key" -o "$work/$name" "$work/artifact/$name.age"
    expected="$(awk -v name="$name" '$2 == name {print $1}' "$work/artifact/SHA256SUMS")"
    [[ "$expected" =~ ^[a-f0-9]{64}$ ]]
    printf '%s\t%s\n' "$service" "$expected" >> "$work/images.tsv"
    (cd "$work" && printf '%s  %s\n' "$expected" "$name" | sha256sum -c -)
    python3 scripts/verify-simulation-oci.py "$work/$name" "$pin"
    skopeo copy --quiet "oci-archive:$work/$name" "docker-daemon:otc-simulation/$service:$pin"
    rm "$work/$name" "$work/artifact/$name.age"
  done
  rm -r "$work/artifact"
done

python3 - "$work/images.tsv" "$RUNNER_TEMP/simulation-images.json" "$GITHUB_SHA" <<'PYLOCK'
import json
from pathlib import Path
import sys
rows = [line.split("\t") for line in Path(sys.argv[1]).read_text().splitlines()]
images = dict(rows)
if len(images) != 16 or len(rows) != len(images):
    raise ValueError("Expected all sixteen candidate images exactly once")
Path(sys.argv[2]).write_text(json.dumps({"deploymentRevision": sys.argv[3], "images": images},
                                       indent=2, sort_keys=True) + "\n")
PYLOCK
