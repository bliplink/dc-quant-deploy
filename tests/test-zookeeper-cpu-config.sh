#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT}" <<'PY'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
env = (root / ".env.example").read_text(encoding="utf-8")
compose = (root / "compose.yaml").read_text(encoding="utf-8")
configs = re.findall(r"(?m)^ZOOKEEPER_CPU_LIMIT=([^\r\n]+)$", env)
assert configs == ["0.50"], "new installs must reserve >=0.50 CPU for ZooKeeper"
matches = re.findall(r"(?m)^    cpus: \$\{ZOOKEEPER_CPU_LIMIT:-([^}]+)\}$", compose)
assert matches == ["0.50"], "Compose ZooKeeper CPU fallback must be 0.50"
assert re.findall(r"(?m)^ZOOKEEPER_CPU_SHARES=([0-9]+)$", env) == ["4096"]
assert compose.count("cpu_shares: ${ZOOKEEPER_CPU_SHARES:-4096}") == 1
assert 'container_name: dc-saas-zookeeper' in compose
assert 'ZOOKEEPER_MEMORY_LIMIT:-384m' in compose
for name in ("MYSQL", "APSSVR"):
    key = name + "_CPU_LIMIT"
    values = re.findall(r"(?m)^" + key + r"=([^\r\n]+)$", env)
    assert values == ["0.75"], key + " must default to 0.75"
    expected = "cpus: ${" + key + ":-0.75}"
    assert compose.count(expected) == 1, key + " Compose default must be 0.75"
print("[zookeeper-cpu-config] PASS: 0.50 ZK, 0.75 MySQL/APSSvr CPU defaults")
PY
