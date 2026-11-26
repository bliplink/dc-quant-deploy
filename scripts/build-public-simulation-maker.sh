#!/usr/bin/env bash
# Admin and Robot use separate historical shared-library versions.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:?expected output directory}"
component="${2:?expected robot or admin-bootstrap}"
case "$component" in
  robot) shared_ref=d3fdaf16a6b8d70e9e81647af459ac6cc4090b37 ;;
  admin-bootstrap) shared_ref=2fa804757c561fc9bbd0642a5c2153fca55cf286 ;;
  *) exit 2 ;;
esac
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"
work="$(mktemp -d "$dest/.funded-maker-XXXXXXXX")"
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
"${maven[@]}" -f "$work/shared/pom.xml" -Dmaven.test.skip=true install
"${maven[@]}" -f "$work/service/pom.xml" package dependency:copy-dependencies -DincludeScope=runtime \
    "-DoutputDirectory=$work/service/target/dependency"
cmp "$work/shared/target/com.app.dc-0.0.4-SNAPSHOT.jar" "$work/service/target/dependency/com.app.dc-0.0.4-SNAPSHOT.jar"
archive="$work/$component.oci.tar"
docker buildx build --platform linux/amd64,linux/arm64 --label "org.opencontainers.image.revision=$pin" \
    --label "dc.simulation.shared-revision=$shared_ref" --label dc.simulation.funded-maker=1 \
    --tag "otc-simulation/$component:$pin" --output "type=oci,dest=$archive" "$work/service"
python3 "$root/scripts/verify-simulation-oci.py" "$archive" "$pin"
mv "$archive" "$dest/$component-$pin.oci.tar"
