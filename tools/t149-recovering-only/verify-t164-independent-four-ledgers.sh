#!/usr/bin/env bash
# T164: independent READ-ONLY original RF2 proof, never READY publication.
set -euo pipefail
[ "$#" -eq 2 ] || { echo "usage: $0 ORIGINAL_T149_DIR NEW_T164_DIR" >&2; exit 2; }
old="$1"; fresh="$2"
[[ "$old" == /* && "$fresh" == /* ]] || exit 1
test "$(basename "$old")" = t149-order-trade-deploy-20261026
test "$(basename "$fresh")" = t164-fresh-e1-runtime-20261026
test -f "$old/.env" && test -f "$fresh/compose.yaml" || exit 1
# Imported local env contains only the existing RSA mount location. Never
# print, copy, or generate any private signing key.
source "$old/.env"
test -f "$EXISTING_RSA_ROOT/public/CommonHaDemoA.pub.der"
test -f "$EXISTING_RSA_ROOT/public/CommonHaDemoB.pub.der"
classroot=/Users/kong/.opentradingcore/t164-fresh-e1-helper-classes-20261026
test -f "$classroot/T164IndependentDualVoterProof.class"
for kind in order trade;do
  if [ "$kind" = order ];then service=OrderSvr;tag=local/otc-t163-ordersvr:original-e1-install-hook
  else service=TradeSvr;tag=local/otc-t164-tradesvr:fenced-trade-replay-fix;fi
  for suffix in a b;do
    node="$kind"svr-"$suffix"
    c="otc-t164-new-original-e1-$node"164-1
    test "$(docker inspect "$c" --format '{{.State.Running}}')" = true
    bindings="$(docker inspect "$c" --format '{{json .HostConfig.PortBindings}}')"
    [[ "$bindings" == "{}" || "$bindings" == null ]]
    ledger="$fresh/data/$node/t164-e1-install/P090/ledger/P090.recovery"
    grep -Fx phase=REPLAY_COMPLETE "$ledger" >/dev/null
  done
  docker run --rm --network otc-t149-ha-intake_test-isolated \
    -v "$classroot:/tmp/t164-classes:ro" \
    -v "$EXISTING_RSA_ROOT/public:/rsa-public:ro" \
    -v "$fresh/data/${kind}svr-a:/voters/a:ro" \
    -v "$fresh/data/${kind}svr-b:/voters/b:ro" \
    --entrypoint java "$tag" \
    -cp "/tmp/t164-classes:/srv/dc/dc/$service/classes:/srv/dc/dc/$service/lib/*" \
    T164IndependentDualVoterProof "$kind"
done
for n in a b;do
  test "$(docker inspect "otc-t84-source-integrated-otc-ha-demo-$n-1" \
    --format '{{.State.Running}}')" = true
done
echo T164_INDEPENDENT_DUAL_RSA_SNAPSHOT_VOTER_BIRTH_LEDGER_ZK_TWO_SERVICES_PASS
echo T164_RECOVERING_ONLY_READY_AND_LIVE_ROBOT_QUOTING_NOT_CERTIFIED