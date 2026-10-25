#!/bin/sh
# Opt-in isolated T107 physical TCP verification. Existing Demo RSA keys ONLY.
# Requires explicit paths; never generates/exports/copies RSA private material.
set -eu
: "${OTC_DEMO_RSA_DIR:?point to ALREADY EXISTING Demo v19-quorum-secrets directory}"
: "${OTC_COMMON_T107_JAR:?locally built Common T107 JAR file path}"
: "${OTC_DC_T107_JAR:?locally built shared DC T107 JAR file path}"
: "${OTC_T107_EVIDENCE_DIR:?output directory for temporary test WAL/custody evidence}"
COUNT=${OTC_T107_COUNT:-30}
case "$COUNT" in ''|*[!0-9]*) echo 'invalid count' >&2;exit 2;; esac
[ "$COUNT" -ge 1 ] && [ "$COUNT" -le 128 ] || { echo 'count must be 1..128' >&2;exit 2; }
[ -f "$OTC_COMMON_T107_JAR" ] && [ -f "$OTC_DC_T107_JAR" ]
[ -f "$OTC_DEMO_RSA_DIR/a/node.pk8" ] && [ -f "$OTC_DEMO_RSA_DIR/b/node.pk8" ]
[ -f "$OTC_DEMO_RSA_DIR/public/CommonHaDemoA.pub.der" ]
[ -f "$OTC_DEMO_RSA_DIR/public/CommonHaDemoB.pub.der" ]
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
umask 077
mkdir -p "$OTC_T107_EVIDENCE_DIR"
classes="$OTC_T107_EVIDENCE_DIR/.compiled-probe-$$"
mkdir "$classes"
net="otc-t107-test-$$"
peer="otc-t107-b-$$"
cleanup(){
  docker rm -f "$peer" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -rf "$classes"
}
trap cleanup EXIT INT TERM
javac -source 8 -target 8 -cp "$OTC_COMMON_T107_JAR:$OTC_DC_T107_JAR" -d "$classes" \
  "$ROOT/T107FreshWalTwoJvmProbe.java"
umask 077
mkdir -p "$OTC_T107_EVIDENCE_DIR/a" "$OTC_T107_EVIDENCE_DIR/b"
[ ! -e "$OTC_T107_EVIDENCE_DIR/a/business.wal" ] &&
 [ ! -e "$OTC_T107_EVIDENCE_DIR/b/business.wal" ] || {
  echo 'refusing to reuse or overwrite previous test WAL evidence' >&2;exit 3;
 }
docker network create --internal "$net" >/dev/null
docker run -d --name "$peer" --network "$net" --read-only --tmpfs /tmp:rw,size=64m \
  --memory 768m --cpus 2 -v "$classes:/probe:ro" \
  -v "$OTC_T107_EVIDENCE_DIR/b:/srv/t106-data:rw" \
  -v "$OTC_DEMO_RSA_DIR/b:/srv/v19/local-identity:ro" \
  -v "$OTC_DEMO_RSA_DIR/public:/srv/v19/identities:ro" \
  --entrypoint java local/otc-t107-tradesvr:fresh-common-03d7f6b \
  -cp '/probe:/srv/dc/dc/TradeSvr/classes:/srv/dc/dc/TradeSvr/lib/*' \
  T107FreshWalTwoJvmProbe server CommonHaDemoB unused >/dev/null
ready=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15;do
  if docker logs "$peer" 2>&1 |grep -q T107_JVM_B_READY_REAL_NETTY_19591;then ready=1;break;fi
  sleep 1
done
[ "$ready" -eq 1 ] || {
  echo 'peer B startup did not complete; test process diagnostics:' >&2
  docker logs --tail 18 "$peer" >&2 || true
  exit 4
}
docker run --rm --network "$net" --read-only --tmpfs /tmp:rw,size=64m \
  --memory 768m --cpus 2 -v "$classes:/probe:ro" \
  -v "$OTC_T107_EVIDENCE_DIR/a:/srv/t106-data:rw" \
  -v "$OTC_DEMO_RSA_DIR/a:/srv/v19/local-identity:ro" \
  -v "$OTC_DEMO_RSA_DIR/public:/srv/v19/identities:ro" \
  --entrypoint java local/otc-t107-ordersvr:fresh-common-f47be93 \
  -cp '/probe:/srv/dc/dc/OrderSvr/classes:/srv/dc/dc/OrderSvr/lib/*' \
  T107FreshWalTwoJvmProbe client CommonHaDemoA "$peer" "$COUNT" \
  |tee "$OTC_T107_EVIDENCE_DIR/result.txt"
a=$(shasum -a 256 "$OTC_T107_EVIDENCE_DIR/a/business.wal"|cut -d ' ' -f 1)
b=$(shasum -a 256 "$OTC_T107_EVIDENCE_DIR/b/business.wal"|cut -d ' ' -f 1)
[ "$a" = "$b" ] || { echo 'physical WAL prefix mismatch across JVMs' >&2;exit 5; }
echo 'T107_COMMON_FILE_WAL_SHA256_MATCH; NOT_ORDER_TRADE_BUSINESS_OR_AUTOMATIC_HA'
