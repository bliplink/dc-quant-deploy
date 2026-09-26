#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
MODE=quick
[[ "${1:-}" != "--full" ]] || MODE=full
[[ "${1:-}" != "--quick" && "${1:-}" != "--full" && -n "${1:-}" ]] && { echo "usage: $0 [--quick|--full]" >&2; exit 2; }
log(){ printf '[saas-acceptance] %s\n' "$*"; }
run(){ local name="$1"; shift; log "START ${name}"; "$@"; log "PASS  ${name}"; }
[[ -r "$ENV_FILE" ]] || { echo "cannot read $ENV_FILE" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a

run 'service log config' "${SCRIPT_DIR}/test-service-log-config.sh"
run 'robot log config' "${SCRIPT_DIR}/test-robot-log-config.sh"
run 'MD cluster config' "${SCRIPT_DIR}/test-md-cluster-config.sh"
run 'Order cluster config' "${SCRIPT_DIR}/test-order-cluster-c-config.sh"
run 'Trade cluster config' "${SCRIPT_DIR}/test-trade-cluster-config.sh"
run 'runtime validation' "${DEPLOY_DIR}/validate-saas.sh" --env-file "$ENV_FILE"

# Fail closed on the HA/recovery errors that previously escaped basic health checks.
for c in dc-saas-tradesvr dc-saas-tradesvr-b dc-saas-projectionsvr; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" == true ]] || { log "FAIL $c is not running"; exit 1; }
done
if docker logs --since 5m dc-saas-tradesvr 2>&1 | grep -Eq 'TRADE_PARTITION_RECOVERY_FAILED|uncommitted journal tail'; then log 'FAIL TradeSvrA recovery errors'; exit 1; fi
if docker logs --since 5m dc-saas-tradesvr-b 2>&1 | grep -Eq 'TRADE_PARTITION_RECOVERY_FAILED|uncommitted journal tail'; then log 'FAIL TradeSvrB recovery errors'; exit 1; fi
if docker logs --since 2m dc-saas-projectionsvr 2>&1 | grep -Eq 'PARTITION_NOT_READY|is not Online'; then log 'FAIL ProjectionSvr sees unroutable partitions'; exit 1; fi
log 'PASS  Trade/Projection recovery log gate'

log 'Checking all 256 Trade partition assignments in ZooKeeper'
PYTHONPATH="${DEPLOY_DIR}" python3 - "${ZOOKEEPER_PORT:-32181}" "${TRADE_CLUSTER_PARTITION_ROOT:-/dc/cluster/tradesvr/partitions}" <<'PYZK'
import sys
from tests.md_cluster_transition_host import DockerZk
from tests.trade_cluster_transition_host import validate_current
port, root = sys.argv[1:]
zk = DockerZk('dc-saas-zookeeper', '127.0.0.1:' + port, root, 'docker')
counts = {'TradeSvrA': 0, 'TradeSvrB': 0}
for i in range(256):
    pid = 'P%03d' % i
    row = zk.read(pid)['value']
    validate_current(row)
    if row.get('partitionId') != pid:
        raise SystemExit('partition identity mismatch: %s -> %r' % (pid, row))
    counts[row['primary']] += 1
if sum(counts.values()) != 256 or not all(counts.values()):
    raise SystemExit('invalid Trade ownership coverage: %r' % counts)
print('trade_partition_coverage=256/256 A=%d B=%d' % (counts['TradeSvrA'], counts['TradeSvrB']))
PYZK
log 'PASS  Trade 256-partition ownership gate'

if [[ "$MODE" == full ]]; then
  [[ -n "${E2E_PASSWORD:-}" ]] || { log 'FAIL E2E_PASSWORD is required for --full'; exit 1; }
  run 'Order cluster state' "${SCRIPT_DIR}/verify-order-cluster-state-host.sh"
  run 'core trading acceptance' "${SCRIPT_DIR}/run-core-trading-acceptance.sh"
  run 'Robot liquidity E2E' "${SCRIPT_DIR}/run-robot-liquidity-e2e-host.sh"
  run 'final runtime validation' "${DEPLOY_DIR}/validate-saas.sh" --env-file "$ENV_FILE"
fi
log "PASS: SaaS ${MODE} acceptance completed"
