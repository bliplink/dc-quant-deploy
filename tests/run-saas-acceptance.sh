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

log 'Checking Trade 256-partition READY evidence at the CURRENT assigned epoch'
a_ready="$(mktemp)"; b_ready="$(mktemp)"; trap 'rm -f "$a_ready" "$b_ready"' EXIT
# A previous A->B->A promotion deliberately leaves historical READY events
# on both nodes. Only current (partition, epoch, primary) is authoritative.
docker logs dc-saas-tradesvr 2>&1 | sed -n 's/.*TRADE_PARTITION_READY node:TradeSvrA, partition:\(P[0-9][0-9][0-9]\), epoch:\([0-9][0-9]*\).*/\1 \2/p' | sort -u > "$a_ready"
docker logs dc-saas-tradesvr-b 2>&1 | sed -n 's/.*TRADE_PARTITION_READY node:TradeSvrB, partition:\(P[0-9][0-9][0-9]\), epoch:\([0-9][0-9]*\).*/\1 \2/p' | sort -u > "$b_ready"
PYTHONPATH="$DEPLOY_DIR" python3 - "$a_ready" "$b_ready" <<'PY'
import collections
import sys
from tests.md_cluster_transition_host import DockerZk

def read_ready(path):
    found = collections.defaultdict(set)
    with open(path, encoding="utf-8") as source:
        for line in source:
            partition, epoch = line.strip().split()
            found[partition].add(int(epoch))
    return found

evidence = {"TradeSvrA": read_ready(sys.argv[1]), "TradeSvrB": read_ready(sys.argv[2])}
control = DockerZk("dc-saas-zookeeper", "127.0.0.1:32181",
                   "/dc/cluster/tradesvr/partitions", "docker")
current = [record["value"] for record in control.read_all(256)]
missing = []
double_ready = []
counts = collections.Counter()
for row in current:
    part, epoch, primary = row["partitionId"], row["epoch"], row["primary"]
    if row.get("state") != "READY" or primary not in evidence:
        missing.append(part + ":invalid-current-assignment")
        continue
    counts[primary] += 1
    if epoch not in evidence[primary].get(part, set()):
        missing.append(part + ":" + primary + ":epoch" + str(epoch))
    other = "TradeSvrB" if primary == "TradeSvrA" else "TradeSvrA"
    if epoch in evidence[other].get(part, set()):
        double_ready.append(part + ":epoch" + str(epoch))
if len(current) != 256 or missing or double_ready:
    raise SystemExit("FAIL Trade current READY evidence: total=%s missing=%s same_epoch_double=%s" %
                     (len(current), missing[:8], double_ready[:8]))
print("[saas-acceptance] PASS  Trade READY coverage 256/256 A=%d B=%d "
      "(current ZK primary and epoch; historical logs ignored)" %
      (counts["TradeSvrA"], counts["TradeSvrB"]))
PY

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