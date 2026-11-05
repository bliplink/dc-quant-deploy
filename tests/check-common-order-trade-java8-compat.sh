#!/usr/bin/env bash
# Common-owned 3-service contract: verify the exact same physical Common JAR
# against ALL Order and Trade sources.  This does not assert operational HA.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON="${OTC_COMMON_JAR:?Pin a complete Common candidate JAR}"
ORDER="${OTC_ORDER_SOURCE_ROOT:?Order source checkout required}"
TRADE="${OTC_TRADE_SOURCE_ROOT:?Trade source checkout required}"
OUT="${OTC_COMPAT_EVIDENCE_ROOT:-$ROOT/.work/t500-allservice-compat-$(date -u +%Y%m%d%H%M%S)}"
M2="${OTC_M2_REPOSITORY:-$HOME/.m2/repository}"
LOMBOK="$M2/org/projectlombok/lombok/1.18.34/lombok-1.18.34.jar"
[[ -s "$COMMON" && -d "$ORDER/src/main/java" && -d "$TRADE/src/main/java" && -s "$LOMBOK" ]] || {
  echo 'COMMON_ALL_SERVICE_REAL_SOURCE_AND_LOMBOK_REQUIRED' >&2;exit 2;
}
for symbol in com.app.common.replication.CommonCertifiedNodeRuntime \
              com.app.common.replication.CommonCertifiedRecoveringBusinessFence \
              com.app.common.replication.CommonCertifiedAutomaticReplicaPlanWiring \
              com.app.common.replication.CommonCertifiedOpaqueRecoveryWindow;do
  javap -classpath "$COMMON" "$symbol" >/dev/null || {
    echo "COMMON_ALL_SERVICE_REQUIRED_SYMBOL_NOT_PACKAGED $symbol" >&2;exit 3;
  }
done
mkdir -p "$OUT"
shasum -a 256 "$COMMON" | tee "$OUT/common-sha256.txt"
# Only use local Maven artifacts; this check does not spend CI quota or
# download/install new third-party dependencies. All source compilations
# use source+target Java8 and explicitly enable the Lombok processor.
LIB=$(find "$M2" -type f -name '*.jar' | grep -vE \
  '/slf4j-(jdk14|log4j12)/1\.5\.6/|/slf4j-log4j12/1\.7\.7/|/slf4j-api/1\.5\.|/junit/junit/' | tr '\n' ':')
for spec in "Order|$ORDER" "Trade|$TRADE";do
  svc="${spec%%|*}"
  checkout="${spec#*|}"
  dest="$OUT/$svc"
  mkdir -p "$dest/classes"
  find "$checkout/src/main/java" -type f -name '*.java' | sort > "$dest/sources.txt"
  CP="$COMMON:$checkout/target/t486-allsource/classes:$checkout/target/classes:$dest/classes:$LIB"
  if ! javac -source 8 -target 8 -processorpath "$LOMBOK" \
          -cp "$CP" -d "$dest/classes" @"$dest/sources.txt" \
          >"$dest/javac.log" 2>&1;then
    echo "COMMON_${svc}_ALLSOURCE_JAVA8_INCOMPATIBLE" >&2
    tail -65 "$dest/javac.log" >&2
    exit 5
  fi
  echo "COMMON_${svc}_ALLSOURCE_JAVA8_COMPATIBLE fileCount=$(wc -l < "$dest/sources.txt" | tr -d ' ')"
done
printf 'COMMON_ALL_SERVICE_JAVA8_CLASSPATH_COMPAT_PASS evidence=%s\n' "$OUT"
