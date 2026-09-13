#!/usr/bin/env bash
set -euo pipefail

ZK_CONTAINER="${ORDER_CLUSTER_ZK_CONTAINER:-dc-saas-zookeeper}"
ZK_ENDPOINT="${ORDER_CLUSTER_ZK_ENDPOINT:-127.0.0.1:32181}"
PARTITION_ROOT="${ORDER_CLUSTER_PARTITION_ROOT:-/dc/cluster/ordersvr/partitions}"
PARTITION_COUNT="${ORDER_CLUSTER_PARTITION_COUNT:-256}"
DATA_ROOT="${ORDER_CLUSTER_DATA_ROOT:-/data/dc-saas-runtime/data}"
WEB_PORT="${WEB_LISTEN_PORT:-18088}"
VERIFY_LEARNERS="${ORDER_CLUSTER_VERIFY_LEARNERS:-false}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '[order-cluster-verify] %s\n' "$*"; }
die() { printf '[order-cluster-verify] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die 'Run with sudo so Docker and runtime state are readable'
command -v docker >/dev/null || die 'docker is required'
command -v python3 >/dev/null || die 'python3 is required'
command -v curl >/dev/null || die 'curl is required'

work_dir="$(mktemp -d)"
trap 'rm -rf -- "${work_dir}"' EXIT
zk_commands="${work_dir}/zk.commands"
zk_output="${work_dir}/zk.output"
assignments="${work_dir}/assignments.jsonl"

for ((index=0; index<PARTITION_COUNT; index++)); do
  printf 'get %s/P%03d\n' "${PARTITION_ROOT}" "${index}" >>"${zk_commands}"
done
printf 'quit\n' >>"${zk_commands}"
docker exec -i "${ZK_CONTAINER}" zkCli.sh -server "${ZK_ENDPOINT}" \
  <"${zk_commands}" >"${zk_output}" 2>&1 || true
grep -o '{"partitionId"[^}]*}' "${zk_output}" >"${assignments}" || true

python3 "${SCRIPT_DIR}/verify_order_cluster_assignments.py" \
  "${assignments}" "${PARTITION_COUNT}" "${DATA_ROOT}" "${VERIFY_LEARNERS}"

route_response="$(curl -fsS --max-time 10 -H 'Content-Type: application/json' \
  --data '{"serverName":"OrderSvr","method":"__cluster_state_verify__","key":"CLUSTER_VERIFY\u001f4\u001fBTCUSDT","content":{"Location":"CLUSTER_VERIFY","MarketIndicator":"4","SecurityID":"BTCUSDT"}}' \
  "http://127.0.0.1:${WEB_PORT}/httpapi/")"
grep -Fq 'is not Online' <<<"${route_response}" && die 'logical OrderSvr route is offline'
grep -Fq 'handler:__cluster_state_verify__ does not exist.' <<<"${route_response}" \
  || die "unexpected logical OrderSvr route response: ${route_response}"

python3 - "${WEB_PORT}" "${PARTITION_COUNT}" <<'PY'
import json
import sys
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

web_port = int(sys.argv[1])
partition_count = int(sys.argv[2])
url = f"http://127.0.0.1:{web_port}/httpapi/"


def representative_key(target):
    nonce = 0
    while True:
        candidate = f"__dc_primary_scan__{target}:{nonce}"
        if zlib.crc32(candidate.encode("utf-8")) % partition_count == target:
            return candidate
        nonce += 1


def verify(target):
    body = json.dumps(
        {
            "serverName": "OrderSvr",
            "method": "__cluster_all_route_verify__",
            "key": representative_key(target),
            "content": {
                "Location": "CLUSTER_VERIFY",
                "MarketIndicator": "4",
                "SecurityID": "BTCUSDT",
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
    except Exception as error:
        return target, f"{type(error).__name__}: {error}"
    expected = "handler:__cluster_all_route_verify__ does not exist."
    if expected not in text or "is not Online" in text:
        return target, text[:240]
    return target, None


failures = []
with ThreadPoolExecutor(max_workers=min(16, partition_count)) as pool:
    futures = [pool.submit(verify, target) for target in range(partition_count)]
    for future in as_completed(futures):
        target, error = future.result()
        if error is not None:
            failures.append((target, error))

if failures:
    for target, error in sorted(failures):
        print(f"P{target:03d} {error}", file=sys.stderr)
    raise SystemExit(
        f"logical OrderSvr partition routes failed: {len(failures)}/{partition_count}"
    )
print(f"logical_partition_routes={partition_count}/{partition_count}")
PY

containers=(dc-saas-ordersvr dc-saas-ordersvr-b dc-saas-gateway)
if grep -qE '"(primary|replica)":"OrderSvrC"|"replicas":\[[^]]*"OrderSvrC"|"learners":\[[^]]*"OrderSvrC"' "${assignments}"; then
  containers+=(dc-saas-ordersvr-c)
fi
for container in "${containers[@]}"; do
  status="$(docker inspect -f '{{.State.Status}}' "${container}")"
  restarts="$(docker inspect -f '{{.RestartCount}}' "${container}")"
  oom="$(docker inspect -f '{{.State.OOMKilled}}' "${container}")"
  image="$(docker inspect -f '{{.Config.Image}}' "${container}")"
  [[ "${status}" == 'running' ]] || die "${container} is ${status}"
  [[ "${oom}" == 'false' ]] || die "${container} was OOM-killed"
  log "${container} image=${image} status=${status} restarts=${restarts} oom=${oom}"
done

log 'PASS: assignments, snapshots, route and container state are consistent.'
