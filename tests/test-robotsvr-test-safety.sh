#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash -n \
  "${ROOT}/tests/restart-order-trade-e2e.sh" \
  "${ROOT}/tests/run-core-trading-stress-host.sh" \
  "${ROOT}/tests/run-trading-rules-e2e-host.sh"

grep -Fq 'E2E_PAUSE_ROBOTSVR:-false' "${ROOT}/tests/restart-order-trade-e2e.sh"
grep -Fq 'LOAD_PAUSE_ROBOTSVR:-false' "${ROOT}/tests/run-core-trading-stress-host.sh"
grep -Fq 'RULE_PAUSE_ROBOTSVR:-false' "${ROOT}/tests/run-trading-rules-e2e-host.sh"

python3 - "${ROOT}" <<'PY2'
from pathlib import Path
import sys
root = Path(sys.argv[1])
checks = {
    'tests/restart-order-trade-e2e.sh': 'pause_robotsvr',
    'tests/run-core-trading-stress-host.sh': 'LOAD_PAUSE_ROBOTSVR',
    'tests/run-trading-rules-e2e-host.sh': 'RULE_PAUSE_ROBOTSVR',
}
for rel, guard in checks.items():
    lines = (root / rel).read_text().splitlines()
    stops = [i for i, line in enumerate(lines) if 'docker stop dc-saas-robotsvr' in line]
    if not stops:
        raise SystemExit(f'{rel}: expected guarded RobotSvr stop path')
    for index in stops:
        context = '\n'.join(lines[max(0, index - 10): index + 1])
        if guard not in context:
            raise SystemExit(f'{rel}:{index+1}: RobotSvr stop is not guarded by {guard}')
print('RobotSvr test safety PASS: shared RobotSvr remains online by default')
PY2
