#!/usr/bin/env bash
set -euo pipefail

source="${1:?usage: build-mac-demo-projection-history.sh PROJECTION_SOURCE NEW_ABSOLUTE_ARTIFACT_DIRECTORY}"
out="${2:?Provide a new absolute artifact directory}"
base="${MAC_DEMO_PROJECTION_BASE:-local/otc-t454-projectionsvr:common-zk-rejoin}"
[[ "$#" == 2 && "$source" == /* && "$out" == /* && ! -e "$out" &&
   "$(uname -s)" == Darwin && "$(docker context show)" == colima ]]
java_home="$(/usr/libexec/java_home -v 1.8)"
base_id="$(docker image inspect "$base" --format '{{.Id}}')"
[[ "$base_id" =~ ^sha256:[a-f0-9]{64}$ ]]
umask 077
mkdir -p "$out/base" "$out/image/classes"
temporary="$(docker create --network none --entrypoint /bin/true "$base_id")"
cleanup(){ docker rm "$temporary" >/dev/null 2>&1 || true; }
trap cleanup EXIT
path=/srv/dc/dc/ProjectionSvr
docker cp "$temporary:$path/classes" "$out/base/classes"
docker cp "$temporary:$path/lib" "$out/base/lib"

pkg=com/app/dc/projection
families=(OrderProjectionService SettledExecutionProjection OrderProjectionSequence
          OrderProjectionBinaryConsumer TradeProjectionBinaryConsumer
          TradeProjectionService CertifiedTradeFinancialReadModel)
inputs=()
for family in "${families[@]}"; do inputs+=("$source/src/main/java/$pkg/$family.java"); done
shasum -a 256 "${inputs[@]}" > "$out/source.sha256"
"$java_home/bin/javac" -source 8 -target 8 -encoding UTF-8 \
  -cp "$out/base/classes:$out/base/lib/*" -d "$out/image/classes" "${inputs[@]}"
for family in "${families[@]}"; do test -s "$out/image/classes/$pkg/$family.class"; done

junit="${HOME}/.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar"
hamcrest="${HOME}/.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar"
test -s "$junit" && test -s "$hamcrest"
test_inputs=()
while IFS= read -r path; do test_inputs+=("$path"); done < <(
  rg --files "$source/src/test/java/com/app/dc/projection" -g '*.java' | LC_ALL=C sort
)
test_classes=()
while IFS= read -r name; do test_classes+=("$name"); done < <(
  python3 - "${test_inputs[@]}" <<'PY'
from pathlib import Path
import re
import sys
for argument in sys.argv[1:]:
    path = Path(argument)
    if path.name.endswith('Test.java'):
        package = re.search(r'^package ([\w.]+);', path.read_text(), re.MULTILINE)
        if package is None:
            raise SystemExit('Projection test has no package')
        print(package[1] + '.' + path.stem)
PY
)
[[ "${#test_inputs[@]}" -gt 0 && "${#test_classes[@]}" -gt 0 ]]
mkdir "$out/test-classes"
test_classpath="$out/test-classes:$out/image/classes:$out/base/classes:$out/base/lib/*:$junit:$hamcrest"
"$java_home/bin/javac" -source 8 -target 8 -encoding UTF-8 -cp "$test_classpath" \
  -d "$out/test-classes" "${test_inputs[@]}" > "$out/test-compile.log" 2>&1
"$java_home/bin/java" -cp "$test_classpath" org.junit.runner.JUnitCore \
  "${test_classes[@]}" > "$out/tests.log" 2>&1
printf 'PASS\n' > "$out/tests.status"
(
  cd "$out/image/classes"
  find "$pkg" -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256
) > "$out/compiled.sha256"
cp "$out/compiled.sha256" "$out/image/compiled.sha256"
digest="$(shasum -a 256 "$out/compiled.sha256" | awk '{print $1}')"
base_short="${base_id#sha256:}"
image="local/otc-mac-demo-projection-history:${base_short:0:12}-${digest:0:12}"
cat > "$out/image/Dockerfile" <<'DOCKERFILE'
ARG BASE
FROM ${BASE}
COPY classes/ /srv/dc/dc/ProjectionSvr/classes/
COPY compiled.sha256 /srv/dc/dc/ProjectionSvr/t554-compiled.sha256
ARG DIGEST
LABEL dc.demo.projection.history.sha256=${DIGEST}
DOCKERFILE
docker build --build-arg "BASE=$base" --build-arg "DIGEST=$digest" -t "$image" "$out/image" > "$out/docker.log" 2>&1
[[ "$(docker image inspect "$base" --format '{{.Id}}')" == "$base_id" ]]
docker run --rm --network none --entrypoint sh "$image" -ec \
  'cd /srv/dc/dc/ProjectionSvr/classes && sha256sum -c ../t554-compiled.sha256' > "$out/image-check.log"
printf 'MAC_DEMO_PROJECTION_IMAGE=%s\nprojection_history_sha256=%s\n' "$image" "$digest" | tee "$out/projection.env"
