#!/usr/bin/env bash
set -euo pipefail

main() {
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
common="${MAC_DEMO_COMMON_SOURCE:-${HOME}/.opentradingcore/t525-common-latest-20261106}"
maven="${MAC_DEMO_MAVEN:-${repo}/.work/t442-maven-tools/apache-maven-3.9.11/bin/mvn}"
candidate="${1:?usage: verify-mac-common-failover.sh CANDIDATE_DIRECTORY SHA256 NEW_ABSOLUTE_RESULTS_DIRECTORY}"
expected_sha="${2:?Provide the exact Common JAR SHA256}"
out="${3:?Provide a new absolute results directory}"
jar="$candidate/common-tested-class-bytes.jar"
[[ "$#" == 3 && "$candidate" == /* && "$out" == /* && ! -e "$out" &&
   "$expected_sha" =~ ^[a-f0-9]{64}$ && -f "$jar" && -f "$candidate/commit.sha" &&
   -f "$candidate/source.sha256" && "$(uname -s)" == Darwin ]] || {
  echo 'Expected a local Mac, an exact Common candidate and a new absolute results directory' >&2
  exit 2
}
[[ "$(shasum -a 256 "$jar" | awk '{print $1}')" == "$expected_sha" ]] || {
  echo 'Common candidate JAR SHA256 mismatch' >&2
  exit 2
}
revision="$(cat "$candidate/commit.sha")"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]]
fixture="$(git -C "$common" rev-parse --verify --end-of-options "${MAC_DEMO_COMMON_P0_FIXTURE_REVISION:-HEAD}^{commit}")"
git -C "$common" diff --quiet "$revision" "$fixture" -- pom.xml src/main || {
  echo 'The fault fixture must use the same production source as the Common candidate' >&2
  exit 2
}

export JAVA_HOME="$(/usr/libexec/java_home -v 1.8)"
umask 077
mkdir -p "$out/source" "$out/runner" "$out/tmp"
printf 'NO_GO\n' > "$out/status"
git -C "$common" archive "$fixture" -- pom.xml src | tar -xf - -C "$out/source"
(
  cd "$out/source"
  { find src -type f -print0; printf 'pom.xml\0'; } |
    LC_ALL=C sort -z | xargs -0 shasum -a 256
) > "$out/fixture-source.sha256"
awk '$2 == "pom.xml" || $2 ~ /^src\/main\//' "$out/fixture-source.sha256" > "$out/main-source.sha256"
awk '$2 == "pom.xml" || $2 ~ /^src\/main\//' "$candidate/source.sha256" | cmp -s "$out/main-source.sha256" - || {
  echo 'Common candidate production source checksums differ' >&2
  exit 2
}
cp "$jar" "$out/common.jar"
[[ "$(shasum -a 256 "$out/common.jar" | awk '{print $1}')" == "$expected_sha" ]]
printf 'common_revision=%s\ncommon_sha256=%s\nfixture_revision=%s\n' \
  "$revision" "$expected_sha" "$fixture" > "$out/candidate.env"

if ! (
  cd "$out/source"
  "$maven" -o -B -DskipTests test-compile dependency:build-classpath "-Dmdep.outputFile=$out/dependencies.classpath"
) > "$out/fixture-build.log" 2>&1; then
  printf 'Common fixture build failed: %s\n' "$out/fixture-build.log" >&2
  exit 2
fi
cat > "$out/runner/VerifyCommonFailover.java" <<'JAVA'
import com.app.common.replication.CommonCertifiedFirstReadyE2AutomaticRecoveryTest;
import com.app.common.replication.CommonCertifiedLivePoisonRecoveryTest;
import com.app.common.replication.VerifiedOpaqueV2SnapshotHeadNettyTest;
import org.junit.internal.TextListener;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

public final class VerifyCommonFailover {
    public static void main(String[] args) {
        boolean nativeOnly = args.length == 1 && "native".equals(args[0]);
        boolean homeOnly = args.length == 1 && "home".equals(args[0]);
        if (!homeOnly) {
        Result snapshot = new JUnitCore().run(Request.method(VerifiedOpaqueV2SnapshotHeadNettyTest.class,
                "rsaSnapshotCanBeReopenedFromDiskAfterTransportCloses"));
        if (!snapshot.wasSuccessful()) {
            System.err.println("FAIL signed snapshot transfer and cold reopen");
            for (Failure failure : snapshot.getFailures()) {
                System.err.println(failure.getTrace());
            }
            System.exit(1);
        }
        JUnitCore junit = new JUnitCore();
        junit.addListener(new TextListener(System.out));
        if (!junit.run(CommonCertifiedLivePoisonRecoveryTest.class).wasSuccessful()) {
            System.err.println("FAIL live poisoned writer recovery and physical voter restarts");
            System.exit(1);
        }
        if (nativeOnly) System.exit(0);
        }
        JUnitCore junit = new JUnitCore();
        junit.addListener(new TextListener(System.out));
        System.exit(junit.run(Request.method(CommonCertifiedFirstReadyE2AutomaticRecoveryTest.class,
                "independentVotersSurviveBothPhysicalCrashesAndReturnHome")).wasSuccessful() ? 0 : 1);
    }
}
JAVA
# Only the candidate provides production classes in the parent and every voter/witness JVM.
classpath="$out/common.jar:$out/source/target/test-classes:$(cat "$out/dependencies.classpath"):$out/runner"
"$JAVA_HOME/bin/javac" -cp "$classpath" -d "$out/runner" "$out/runner/VerifyCommonFailover.java"
if [[ "${MAC_DEMO_COMMON_PARALLEL_P0_JVMS:-false}" == true ]]; then
  # Independent ZooKeeper servers, volumes, ports and JVM statics. All 13
  # native fault cases remain sequential in their original single JVM.
  # The complete 256-partition exercise runs unchanged in a second JVM.
  mkdir "$out/tmp/native" "$out/tmp/home"
  "$JAVA_HOME/bin/java" "-Djava.io.tmpdir=$out/tmp/native" -Dcommon.node.control.debug=true \
    "-Dt554.fixture.evidence.directory=$out/process-evidence" \
    -cp "$classpath" VerifyCommonFailover native > "$out/native-faults.log" 2>&1 &
  native_pid=$!
  "$JAVA_HOME/bin/java" "-Djava.io.tmpdir=$out/tmp/home" -Dcommon.node.control.debug=true \
    "-Dt554.fixture.evidence.directory=$out/process-evidence" \
    -Dt554.verify.third.crash=true -Dt554.verify.repeated.return=true \
    "-Dt554.verify.interrupted.return=${MAC_DEMO_REQUIRE_INTERRUPTED_RETURN:-false}" \
    -cp "$classpath" VerifyCommonFailover home > "$out/home-faults.log" 2>&1 &
  home_pid=$!
  native_exit=0
  home_exit=0
  wait "$native_pid" || native_exit=$?
  wait "$home_pid" || home_exit=$?
  python3 - "$out" "$native_pid" "$home_pid" "$native_exit" "$home_exit" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
stages=[]
for name,pid,code,file in [('native',sys.argv[2],sys.argv[4],'native-faults.log'),
                           ('home',sys.argv[3],sys.argv[5],'home-faults.log')]:
    stages.append({'name':name,'pid':int(pid),'exit_code':int(code),'log':file,
                   'sha256':hashlib.sha256((root/file).read_bytes()).hexdigest()})
(root/'independent-jvm-stages.json').write_text(json.dumps({'scope':'Same exact Common JAR; private fixtures; original cases unchanged',
                                                          'stages':stages},indent=2)+'\n')
PY
  cat "$out/native-faults.log" "$out/home-faults.log" | tee "$out/failover.log"
  [[ "$native_exit" == 0 && "$home_exit" == 0 ]] || return 1
else
"$JAVA_HOME/bin/java" "-Djava.io.tmpdir=$out/tmp" -Dcommon.node.control.debug=true \
  "-Dt554.fixture.evidence.directory=$out/process-evidence" \
  -Dt554.verify.third.crash=true -Dt554.verify.repeated.return=true \
  "-Dt554.verify.interrupted.return=${MAC_DEMO_REQUIRE_INTERRUPTED_RETURN:-false}" \
  -cp "$classpath" VerifyCommonFailover 2>&1 | tee "$out/failover.log"
fi
python3 "$repo/scripts/finalize-mac-common-failover.py" "$candidate" "$expected_sha" "$out"
}

main "$@"
