#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
MODE=quick
RUNNING=false
STAGE=all
for arg in "$@"; do
  case "$arg" in
    --full) MODE=full ;;
    --quick) MODE=quick ;;
    --running) RUNNING=true ;;
    --stage=*) STAGE="${arg#--stage=}" ;;
    *) echo "usage: $0 [--quick|--full] [--running] [--stage=core|robot|all]" >&2; exit 2 ;;
  esac
done
log(){ printf '[saas-acceptance] %s\n' "$*"; }
# Local acceptance endpoints must bypass any developer/host HTTP proxy.
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="${NO_PROXY}"
run(){ local name="$1"; shift; log "START ${name}"; "$@"; log "PASS  ${name}"; }
run 'service log config' "${SCRIPT_DIR}/test-service-log-config.sh"
run 'robot log config' "${SCRIPT_DIR}/test-robot-log-config.sh"
run 'MD cluster config' "${SCRIPT_DIR}/test-md-cluster-config.sh"
run 'Order cluster config' "${SCRIPT_DIR}/test-order-cluster-c-config.sh"
run 'Trade cluster config' "${SCRIPT_DIR}/test-trade-cluster-config.sh"
if [[ -r "$ENV_FILE" ]]; then
  set -a; . "$ENV_FILE"; set +a
  if [[ "$MODE" == full && -z "${E2E_PASSWORD:-}" ]]; then
    E2E_PASSWORD="${LOGIN_DEFAULT_PASSWORD:-}"
    export E2E_PASSWORD
  fi
elif [[ "$RUNNING" != true ]]; then
  echo "cannot read $ENV_FILE (use --running to validate an existing deployment)" >&2; exit 1
fi

if [[ "$RUNNING" == true && ! -r "$ENV_FILE" ]]; then
  log 'SKIP  env-file runtime validation; using running-container gates'
else
  run 'runtime validation' "${DEPLOY_DIR}/validate-saas.sh" --env-file "$ENV_FILE"
fi

# Fail closed on the HA/recovery errors that previously escaped basic health checks.
for c in dc-saas-tradesvr dc-saas-tradesvr-b dc-saas-projectionsvr; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" == true ]] || { log "FAIL $c is not running"; exit 1; }
done
if docker logs --since 5m dc-saas-tradesvr 2>&1 | grep -Eq 'TRADE_PARTITION_RECOVERY_FAILED|uncommitted journal tail'; then log 'FAIL TradeSvrA recovery errors'; exit 1; fi
if docker logs --since 5m dc-saas-tradesvr-b 2>&1 | grep -Eq 'TRADE_PARTITION_RECOVERY_FAILED|uncommitted journal tail'; then log 'FAIL TradeSvrB recovery errors'; exit 1; fi
if docker logs --since 2m dc-saas-projectionsvr 2>&1 | grep -Eq 'PARTITION_NOT_READY|is not Online'; then log 'FAIL ProjectionSvr sees unroutable partitions'; exit 1; fi
log 'PASS  Trade/Projection recovery log gate'

log 'Checking Trade 256-partition READY evidence'
a_ready="$(mktemp)"; b_ready="$(mktemp)"; trap 'rm -f "$a_ready" "$b_ready"' EXIT
docker logs dc-saas-tradesvr 2>&1 | sed -n 's/.*TRADE_PARTITION_READY node:TradeSvrA, partition:\(P[0-9][0-9][0-9]\).*/\1/p' | sort -u > "$a_ready"
docker logs dc-saas-tradesvr-b 2>&1 | sed -n 's/.*TRADE_PARTITION_READY node:TradeSvrB, partition:\(P[0-9][0-9][0-9]\).*/\1/p' | sort -u > "$b_ready"
a_count="$(wc -l < "$a_ready" | tr -d ' ')"; b_count="$(wc -l < "$b_ready" | tr -d ' ')"
total="$(cat "$a_ready" "$b_ready" | sort -u | wc -l | tr -d ' ')"; overlap="$(comm -12 "$a_ready" "$b_ready" | wc -l | tr -d ' ')"
[[ "$a_count" -gt 0 && "$b_count" -gt 0 && "$total" -eq 256 && "$overlap" -eq 0 ]] || { log "FAIL Trade READY coverage A=$a_count B=$b_count total=$total overlap=$overlap"; exit 1; }
log "PASS  Trade READY coverage 256/256 A=$a_count B=$b_count"

if [[ "$MODE" == full ]]; then
  [[ -n "${E2E_PASSWORD:-}" ]] || { log 'FAIL E2E_PASSWORD is required for --full'; exit 1; }
  run 'Order cluster state' bash "${SCRIPT_DIR}/verify-order-cluster-state-host.sh"
  if [[ "${STAGE}" == all || "${STAGE}" == core ]]; then
    run 'core trading acceptance' bash "${SCRIPT_DIR}/run-core-trading-acceptance.sh"
  fi
  if [[ "${STAGE}" == all || "${STAGE}" == robot ]]; then
    ROBOT_E2E_PASSWORD="${ROBOT_E2E_PASSWORD:-${E2E_PASSWORD}}" run 'Robot liquidity E2E' bash "${SCRIPT_DIR}/run-robot-liquidity-e2e-host.sh"
  fi
  run 'final runtime validation' "${DEPLOY_DIR}/validate-saas.sh" --env-file "$ENV_FILE"
fi
log "PASS: SaaS ${MODE} acceptance completed"
