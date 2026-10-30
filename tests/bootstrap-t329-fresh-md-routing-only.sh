#!/usr/bin/env bash
set -euo pipefail
# T329 fresh Demo only; this is the existing Mac installer MD **route
# metadata** bootstrap, NOT signed Common Order/Trade quorum READY.
# MD must still retrieve Image from Order; never count this as trading PASS.
ZK=otc-t84-source-integrated-otc-ha-zk1-1
DIR=/dc/cluster/mdsvr/partitions
call_zk() { docker exec -i "$ZK" sh -c 'zkCli.sh -server 127.0.0.1:2181' 2>&1; }
for node in A B C; do
  register="$(printf 'ls /MDTService/MDSvr%s\nquit\n' "$node" | call_zk)"
  grep -F "MDSvr$node]" <<<"$register" >/dev/null || {
    echo "T329_MD_BOOTSTRAP_FENCED_NO_NODE=$node" >&2; exit 3;
  }
done
# ZooKeeper CLI exits 1 for an expected absent fresh root.
existing="$(printf 'ls %s\nquit\n' "$DIR" | call_zk || true)"
if grep -q '\[P000' <<<"$existing";then
  count="$(grep -oE 'P[0-9]{3}' <<<"$existing" | sort -u | wc -l | tr -d ' ')"
  [ "$count" = 256 ] || { echo "T329_MD_PARTIAL_EXISTING_ROUTE_DENIED=$count" >&2; exit 4; }
  echo "T329_ORIGINAL_MD_ROUTE_BOOTSTRAP_ALREADY_COMPLETE partitions=256"
  exit 0
fi
grep -q "Node does not exist: $DIR" <<<"$existing" || {
  echo "T329_MD_FOREIGN_ROUTE_DIRECTORY_DENIED" >&2; exit 5;
}
commands="$(mktemp)"
output="$(mktemp)"
trap 'rm -f "$commands" "$output"' EXIT
{
  printf 'create /dc x\ncreate /dc/cluster x\ncreate /dc/cluster/mdsvr x\n'
  printf 'create %s x\n' "$DIR"
  for ((i=0;i<256;i++));do
    if ((i%2==0));then primary=MDSvrA; replica=MDSvrB
    else primary=MDSvrB; replica=MDSvrA;fi
    printf 'create %s/P%03d {"partitionId":"P%03d","epoch":1,"primary":"%s","replica":"%s","learners":["MDSvrC"],"state":"READY"}\n' "$DIR" "$i" "$i" "$primary" "$replica"
  done
  printf 'quit\n'
} > "$commands"
call_zk < "$commands" > "$output" || {
  tail -20 "$output" >&2; exit 6;
}
if grep -Eq 'KeeperErrorCode = (NoAuth|InvalidACL|ConnectionLoss|SessionExpired|BadVersion)' "$output";then
  tail -20 "$output" >&2; exit 7;
fi
after="$(printf 'ls %s\nget %s/P081\nquit\n' "$DIR" "$DIR" | call_zk)"
count="$(grep -oE 'P[0-9]{3}' <<<"$after" | sort -u | wc -l | tr -d ' ')"
[ "$count" = 256 ] || { echo "T329_MD_ROUTE_BOOTSTRAP_NOT_COMPLETE=$count" >&2; exit 8; }
grep -F '"primary":"MDSvrB"' <<<"$after" >/dev/null || exit 9
echo "T329_ORIGINAL_MD_ROUTE_METADATA_BOOTSTRAP_PASS 256/256 A_B primary, C learner, E1; imageAndTrades=UNTESTED"
