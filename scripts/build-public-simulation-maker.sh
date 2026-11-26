#!/usr/bin/env bash
# Build each service with the shared library pinned for its runtime.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:?expected output directory}"
component="${2:?expected service name}"
shared_ref="$(awk -v service="$component" '$1 == service {print $2}' "$root/config/public-simulation-service-pins.tsv")"
[[ "$shared_ref" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid service pin for $component" >&2; exit 2; }
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"
work="$(mktemp -d "$dest/.service-XXXXXXXX")"
trap 'rm -rf "$work"' EXIT
mkdir "$work/shared" "$work/service"
git -C "$root/sources/shared" archive "$shared_ref" | tar -x -C "$work/shared"
pin="$(git -C "$root" rev-parse "HEAD:sources/$component")"
git -C "$root/sources/$component" archive "$pin" | tar -x -C "$work/service"
if [[ "$component" == admin-bootstrap ]]; then
  stats="$(git -C "$root" rev-parse HEAD:sources/admin-public-stats)"
  for path in src/main/java/com/app/dc/service/PublicTenantDirectoryService.java src/test/java/com/app/dc/service/PublicTenantDirectoryServiceTest.java; do
    git -C "$root/sources/admin-public-stats" show "$stats:$path" > "$work/service/$path"
  done
fi
maven=(mvn -B -ntp "-Dmaven.repo.local=$work/m2")
if [[ "$component" == price-feed ]]; then
  mkdir "$work/futures"
  git -C "$root/sources/futures-connector" archive "$(git -C "$root" rev-parse HEAD:sources/futures-connector)" | tar -x -C "$work/futures"
  "${maven[@]}" -f "$work/futures/pom.xml" install
fi
"${maven[@]}" -f "$work/shared/pom.xml" -Dmaven.test.skip=true install
"${maven[@]}" -f "$work/service/pom.xml" package dependency:copy-dependencies -DincludeScope=runtime \
    "-DoutputDirectory=$work/service/target/dependency"
cmp "$work/shared/target/com.app.dc-0.0.4-SNAPSHOT.jar" "$work/service/target/dependency/com.app.dc-0.0.4-SNAPSHOT.jar"
archive="$work/$component.oci.tar"
labels=(--label "dc.simulation.shared-revision=$shared_ref")
case "$component" in
  robot|admin-bootstrap) labels+=(--label dc.simulation.funded-maker=1) ;;
esac
docker buildx build --platform linux/amd64,linux/arm64 --label "org.opencontainers.image.revision=$pin" \
    "${labels[@]}" \
    --tag "otc-simulation/$component:$pin" --output "type=oci,dest=$archive" "$work/service"
python3 "$root/scripts/verify-simulation-oci.py" "$archive" "$pin"
mv "$archive" "$dest/$component-$pin.oci.tar"
