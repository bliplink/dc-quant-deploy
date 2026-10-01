#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${DEPLOY_DIR}/.env.prod}"
if [[ -r "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

ZK_CONTAINER="${ORDER_CLUSTER_ZK_CONTAINER:-dc-saas-zookeeper}"
ZK_ENDPOINT="${ORDER_CLUSTER_ZK_ENDPOINT:-127.0.0.1:32181}"
PARTITION_ROOT="${ORDER_CLUSTER_PARTITION_ROOT:-/dc/cluster/ordersvr/partitions}"
PARTITION_COUNT="${ORDER_CLUSTER_PARTITION_COUNT:-256}"
DATA_ROOT="${ORDER_CLUSTER_DATA_ROOT:-/data/dc-saas-runtime/data}"
WEB_PORT="${WEB_LISTEN_PORT:-18088}"
VERIFY_LEARNERS="${ORDER_CLUSTER_VERIFY_LEARNERS:-false}"
VERIFY_SESSION_ID="${ORDER_CLUSTER_VERIFY_SESSION_ID:-}"
ALLOW_AUTH_SKIP="${ORDER_CLUSTER_VERIFY_ALLOW_AUTH_SKIP:-false}"

log() { printf '[order-cluster-verify] %s\n' "$*"; }
die() { printf '[order-cluster-verify] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die 'docker is required'
docker inspect "${ZK_CONTAINER}" >/dev/null 2>&1 || die 'Docker/ZooKeeper is not readable; run with sufficient permission (sudo on Linux when required)'
command -v python3 >/dev/null || die 'python3 is required'
command -v curl >/dev/null || die 'curl is required'
[[ "${ALLOW_AUTH_SKIP}" == true || "${ALLOW_AUTH_SKIP}" == false ]] ||
  die 'ORDER_CLUSTER_VERIFY_ALLOW_AUTH_SKIP must be true or false'

if [[ -z "${VERIFY_SESSION_ID}" && "${ALLOW_AUTH_SKIP}" != true ]]; then
  [[ -n "${DEFAULT_E2E_ADMIN_PASSWORD:-}" ]] ||
    die 'authenticated route scan requires ORDER_CLUSTER_VERIFY_SESSION_ID or DEFAULT_E2E_ADMIN_PASSWORD'
  VERIFY_SESSION_ID="$(python3 - "${WEB_PORT}" <<'PY'
import json
import os
import sys
import urllib.request

port = sys.argv[1]
username = os.environ.get("DEFAULT_E2E_ADMIN_USERNAME", "tenantadmin")
location = os.environ.get("DEFAULT_E2E_LOCATION", "E2E001")
request = {
    "serverName": "LoginSvr",
    "method": "SYS.ATS.LOGIN",
    "content": {
        "method": "login",
        "cid": "ORDER_CLUSTER_VERIFY",
        "user_id": username,
        "user_name": username,
        "password": os.environ["DEFAULT_E2E_ADMIN_PASSWORD"],
        "client_type": "Manager",
        "Location": location,
    },
}
try:
    body = json.dumps(request, separators=(",", ":")).encode()
    http = urllib.request.Request(
        "http://127.0.0.1:{}/httpapi/".format(port), data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(http, timeout=30) as response:
        payload = json.load(response)
    token = (payload.get("data") or {}).get("token")
    if payload.get("code") != 0 or not token:
        raise ValueError("login code {}".format(payload.get("code")))
    print(token)
except Exception as error:
    print("authenticated route scan login failed: {}".format(error), file=sys.stderr)
    sys.exit(1)
PY
)" || die 'cannot obtain authenticated OrderSvr verification session'
fi

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
# ZK CAS writers need not serialize partitionId as the first JSON field.
grep -oE '\{[^}]*"partitionId"[^}]*\}' "${zk_output}" >"${assignments}" || true

verify_data_root="${DATA_ROOT}"
if [[ ! -d "${verify_data_root}" ]]; then
  # Colima/macOS: avoid copying the entire journal tree. Materialize only the
  # 256 small snapshot.json files required by the same verifier. Linux keeps
  # using DATA_ROOT directly.
  verify_data_root="${work_dir}/runtime-data"
  for node in OrderSvrA OrderSvrB; do
    mkdir -p "${verify_data_root}/${node}/snapshot"
    docker exec dc-saas-ordersvr sh -lc "cd /srv/dc/data/${node}/snapshot && tar -cf - P*/snapshot.json" |
      tar -xf - -C "${verify_data_root}/${node}/snapshot"
  done
fi
python3 "${SCRIPT_DIR}/verify_order_cluster_assignments.py" \
  "${assignments}" "${PARTITION_COUNT}" "${verify_data_root}" "${VERIFY_LEARNERS}"

curl_headers=(-H 'Content-Type: application/json')
if [[ -n "${VERIFY_SESSION_ID}" ]]; then
  curl_headers+=(-H "sessionId: ${VERIFY_SESSION_ID}")
fi
route_response="$(curl -fsS --max-time 10 "${curl_headers[@]}" \
  --data '{"serverName":"OrderSvr","method":"__cluster_state_verify__","key":"CLUSTER_VERIFY\u001f4\u001fBTCUSDT","content":{"Location":"CLUSTER_VERIFY","MarketIndicator":"4","SecurityID":"BTCUSDT"}}' \
  "http://127.0.0.1:${WEB_PORT}/httpapi/")"
grep -Fq 'is not Online' <<<"${route_response}" && die 'logical OrderSvr route is offline'
auth_required=false
if grep -Fq 'AUTHENTICATED_SESSION_REQUIRED' <<<"${route_response}"; then
  [[ -z "${VERIFY_SESSION_ID}" ]] || die "authenticated OrderSvr verification session was rejected"
  auth_required=true
  [[ "${ALLOW_AUTH_SKIP}" == true ]] || die 'unauthenticated partition route scan cannot be reported as PASS'
  log 'PARTIAL: bootstrap-only; unauthenticated partition HTTP scan skipped.'
elif ! grep -Fq 'handler:__cluster_state_verify__ does not exist.' <<<"${route_response}"; then
  die "unexpected logical OrderSvr route response: ${route_response}"
fi

if [[ "${auth_required}" != true ]]; then
python3 - "${WEB_PORT}" "${PARTITION_COUNT}" "${VERIFY_SESSION_ID}" <<'PY'
import json
import sys
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

web_port = int(sys.argv[1])
partition_count = int(sys.argv[2])
session_id = sys.argv[3]
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
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["sessionId"] = session_id
    request = urllib.request.Request(url, data=body, headers=headers)
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
fi

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

if [[ "${auth_required}" == true ]]; then
  log 'PARTIAL: assignments, snapshots and containers verified; partition routes NOT verified.'
else
  log 'PASS: assignments, snapshots, authenticated routes and container state are consistent.'
fi
