#!/usr/bin/env bash
# T155 READ-ONLY preflight for replacing REAL Demo Order/Trade and resuming Robot.
# This is NOT a deployment command and does NOT publish business READY.
# Exit 0 only after external authenticated business readiness and actual
# transactional verification have been supplied by a future trusted verifier.
set -euo pipefail

serviceNames=(ordersvr-a ordersvr-b ordersvr-c tradesvr-a tradesvr-b)
liveServices=(dc-saas-ordersvr dc-saas-ordersvr-b dc-saas-ordersvr-c dc-saas-tradesvr dc-saas-tradesvr-b)
failures=0

fail() {
  printf 'T155_NO_GO %s\n' "$1"
  failures=$((failures+1))
}
need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'T155_DENIED missing_command=%s\n' "$1" >&2
    exit 2
  fi
}
need_cmd docker
need_cmd grep

for service in "${liveServices[@]}"; do
  status="$(docker inspect "$service" --format '{{.State.Running}}' 2>/dev/null || true)"
  if [ "$status" != true ]; then
    printf "T155_CURRENT_DEMO_OUTAGE service_stopped=%s\\n" "$service"
  fi
done
for n in "${serviceNames[@]}"; do
  candidate="otc-t149-ha-intake-$n-1"
  image="$(docker inspect "$candidate" --format '{{.Config.Image}}' 2>/dev/null || true)"
  running="$(docker inspect "$candidate" --format '{{.State.Running}}' 2>/dev/null || true)"
  case "$n" in ordersvr*) expected=local/otc-t153-ordersvr:common-e1-candidate ;;
    tradesvr*) expected=local/otc-t153-tradesvr:common-e1-candidate ;;
  esac
  if [ "$running" != true ] || [ "$image" != "$expected" ]; then
    fail "isolated_candidate_not_current=$candidate"
    continue
  fi
  case "$n" in
    ordersvr*) business=OrderSvr; prefix=order ;;
    tradesvr*) business=TradeSvr; prefix=trade ;;
  esac
  phase="$(docker exec "$candidate" sh -c     "grep -E '^$prefix.common.nodeRuntime.phase=' '/srv/dc/dc/$business/config/application.properties'" 2>/dev/null     | tail -1 | cut -d= -f2 || true)"
  if [ "$phase" != "READY" ]; then
    fail "candidate_not_business_ready=$n phase=${phase:-unknown}"
  fi
done

for n in zk1 zk2 zk3; do
  alive="$(docker inspect "otc-t149-ha-intake-$n-1" --format '{{.State.Running}}' 2>/dev/null || true)"
  if [ "$alive" != true ]; then fail "isolated_zk_not_running=$n"; fi
done

robot="$(docker inspect dc-saas-robotsvr --format '{{.State.Running}}' 2>/dev/null || true)"
gateway="$(docker inspect dc-saas-gateway --format '{{.State.Running}}' 2>/dev/null || true)"
if [ "$robot" != true ] || [ "$gateway" != true ]; then
  fail "robot_or_gateway_stopped"
fi

# Method-level error counts, not request bodies, tenant IDs, API keys or logs.
# This makes the existing user-facing outage visible without exposing secrets.
if [ "$gateway" = true ]; then
  recent="$(docker logs --since 25s --tail 3000 dc-saas-gateway 2>&1 |     grep -E 'GW_METHOD_CALL_FAIL.*method=(queryOpenOrder|queryTradePosition)' || true)"
  orders="$(printf '%s\n' "$recent" | grep -c 'method=queryOpenOrder' || true)"
  positions="$(printf '%s\n' "$recent" | grep -c 'method=queryTradePosition' || true)"
  printf 'T155_GATEWAY_CURRENT_25S_ERRORS queryOpenOrder=%s queryTradePosition=%s\n' "$orders" "$positions"
fi

# A READY string / process UP still is not signed voter proof or authenticated
# state install, durable replay and cross-JVM acceptance. No known current
# T153 runtime integrates these sources: never silently approve the swap.
fail 'missing_verified_recovery_install_ledger_and_original_zero_WAL_Custody'
fail 'missing_same_session_Common_ZK_certified_READY_and_new_business_JVM_probe'
fail 'missing_real_Order_Trade_robot_order_fill_balance_position_Projection_reconciliation'

printf 'T155_DEMO_ORDER_TRADE_ROBOT_SWAP_BLOCKED failing_gates=%d\n' "$failures"
printf '%s\n' 'T155_NO_CHANGES: no Docker recreate, ZK CAS, Robot restart or Gateway routing mutation'
exit 3