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

log 'Checking Trade 256-partition current READY evidence'
trade_ready_dir="$(mktemp -d)"
trap 'rm -rf "$trade_ready_dir"' EXIT
trade_partition_root="${TRADE_CLUSTER_PARTITION_ROOT:-/dc/cluster/tradesvr/partitions}"
trade_zk_server="127.0.0.1:${ZOOKEEPER_PORT:-32181}"
trade_zk_commands="$trade_ready_dir/zk.commands"
trade_zk_output="$trade_ready_dir/zk.output"
trade_a_log="$trade_ready_dir/trade-a.log"
trade_b_log="$trade_ready_dir/trade-b.log"
for ((index=0; index<256; index++)); do
  printf 'get -s %s/P%03d\n' "$trade_partition_root" "$index" >>"$trade_zk_commands"
done
printf 'quit\n' >>"$trade_zk_commands"
docker exec -i dc-saas-zookeeper zkCli.sh -server "$trade_zk_server"   <"$trade_zk_commands" >"$trade_zk_output" 2>&1 || true
docker logs dc-saas-tradesvr >"$trade_a_log" 2>&1
docker logs dc-saas-tradesvr-b >"$trade_b_log" 2>&1
if ! trade_ready_summary="$(python3 - "$trade_zk_output" "$trade_a_log" "$trade_b_log" <<'PY'
import json
import re
import sys

zk_path, a_log_path, b_log_path = sys.argv[1:]
assignments = {}
for raw in open(zk_path, encoding="utf-8", errors="ignore"):
    line = raw.strip()
    if not line.startswith("{") or '"partitionId"' not in line:
        continue
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        continue
    partition_id = str(value.get("partitionId") or "")
    if re.fullmatch(r"P\d{3}", partition_id):
        assignments[partition_id] = value

expected = [f"P{i:03d}" for i in range(256)]
if sorted(assignments) != expected:
    missing = sorted(set(expected) - set(assignments))
    extra = sorted(set(assignments) - set(expected))
    raise SystemExit(
        f"expected 256 current Trade assignments, found {len(assignments)} "
        f"missing={missing[:8]} extra={extra[:8]}"
    )

ready = set()
pattern = re.compile(
    r"TRADE_PARTITION_READY node:(TradeSvr[AB]), partition:(P\d{3}), epoch:(\d+)"
)
for node, path in (("TradeSvrA", a_log_path), ("TradeSvrB", b_log_path)):
    for raw in open(path, encoding="utf-8", errors="ignore"):
        match = pattern.search(raw)
        if match and match.group(1) == node:
            ready.add((node, match.group(2), int(match.group(3))))

primary_counts = {"TradeSvrA": 0, "TradeSvrB": 0}
errors = []
for partition_id in expected:
    value = assignments[partition_id]
    state = str(value.get("state") or "")
    primary = str(value.get("primary") or "")
    try:
        epoch = int(value.get("epoch"))
    except (TypeError, ValueError):
        errors.append(f"{partition_id}:invalid_epoch={value.get('epoch')!r}")
        continue
    if state != "READY":
        errors.append(f"{partition_id}:state={state}")
        continue
    if primary not in primary_counts:
        errors.append(f"{partition_id}:primary={primary}")
        continue
    primary_counts[primary] += 1
    if (primary, partition_id, epoch) not in ready:
        errors.append(f"{partition_id}:missing_READY node={primary} epoch={epoch}")

if errors:
    raise SystemExit("current Trade READY verification failed: " + "; ".join(errors[:12]))

print(
    f"256/256 A={primary_counts['TradeSvrA']} B={primary_counts['TradeSvrB']}"
)
PY
)"; then
  log 'FAIL Trade current READY verification'
  exit 1
fi
log "PASS  Trade current READY coverage ${trade_ready_summary}"

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
